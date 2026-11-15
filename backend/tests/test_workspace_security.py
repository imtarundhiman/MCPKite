import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import create_app
from app.models import ServerDefinition, ServerSecret, User, Workspace, WorkspaceMembership
from app.security import decode_access_token

JWT_SECRET = "test-signing-key-that-is-at-least-32-bytes"
PASSWORD = "secure-test-password-2026"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}


def _client(tmp_path):
    database_path = tmp_path / "workspace.db"
    return TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{database_path}",
            initialize_schema=True,
            jwt_secret=JWT_SECRET,
        )
    )


def _csrf(client):
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return response.json()["csrf_token"]


def _register(
    client,
    *,
    email,
    display_name=None,
    workspace_name=None,
    invite_token=None,
):
    csrf_token = _csrf(client)
    response = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": display_name or email.partition("@")[0],
            "workspace_name": workspace_name,
            "invite_token": invite_token,
        },
    )
    return csrf_token, response


def _seed_other_workspace(database_path, *, with_secret=False, with_server=False):
    async def seed():
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        workspace_id = uuid4().hex
        user_id = str(uuid4())
        server_id = str(uuid4()) if with_server else None
        async with session_factory() as session:
            session.add_all(
                [
                    Workspace(
                        id=workspace_id,
                        name="Other workspace",
                        bootstrap_key=uuid4().hex,
                        created_at=now,
                    ),
                    User(
                        id=user_id,
                        email=f"{user_id}@example.com",
                        display_name=user_id,
                        password_hash="unused-test-password-hash",
                        created_at=now,
                    ),
                    WorkspaceMembership(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        role="owner",
                        created_at=now,
                    ),
                ]
            )
            if server_id is not None:
                session.add(
                    ServerDefinition(
                        id=server_id,
                        workspace_id=workspace_id,
                        name="Other workspace server",
                        description="Not visible to the current workspace.",
                        created_at=now,
                        endpoint_path=f"/mcp/{uuid4()}/",
                        auth_required=False,
                    )
                )
            if with_secret:
                session.add(
                    ServerSecret(
                        id=str(uuid4()),
                        workspace_id=workspace_id,
                        server_id=None,
                        name="Other workspace secret",
                        token_hash="a" * 64,
                        created_at=now,
                    )
                )
            await session.commit()
        await engine.dispose()
        return server_id

    return asyncio.run(seed())


def _mcp_result(response):
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        body = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ")
        )
    return json.loads(body)["result"]


def test_signup_issues_http_only_jwt_and_csrf_protected_management(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            display_name="  Studio Owner  ",
            workspace_name="Studio Team",
        )

        assert registered.status_code == 201
        assert registered.json()["display_name"] == "Studio Owner"
        assert registered.json()["role"] == "owner"
        assert registered.json()["workspace_name"] == "Studio Team"
        cookie_headers = registered.headers.get_list("set-cookie")
        assert any("studio_access=" in item and "httponly" in item.lower() for item in cookie_headers)
        assert any("studio_refresh=" in item and "httponly" in item.lower() for item in cookie_headers)
        access_token = client.cookies.get("studio_access")
        assert access_token is not None
        access_claims = decode_access_token(access_token, JWT_SECRET)
        assert access_claims["iss"] == "mcpkite"
        assert access_claims["aud"] == "mcpkite-api"
        assert client.get("/openapi.json").json()["info"]["title"] == "MCPKite"
        assert client.get("/api/v1/auth/me").status_code == 200

        rejected = client.post("/api/v1/servers", json={"name": "No CSRF"})
        assert rejected.status_code == 403
        accepted = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "CSRF protected"},
        )
        assert accepted.status_code == 201


def test_display_name_update_is_validated_persisted_and_csrf_protected(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            display_name="Studio Owner",
            workspace_name="Studio Team",
        )
        assert registered.status_code == 201

        rejected = client.patch(
            "/api/v1/auth/me",
            json={"display_name": "No CSRF"},
        )
        assert rejected.status_code == 403

        blank_name = client.patch(
            "/api/v1/auth/me",
            headers={"X-CSRF-Token": csrf_token},
            json={"display_name": "   "},
        )
        assert blank_name.status_code == 422

        updated = client.patch(
            "/api/v1/auth/me",
            headers={"X-CSRF-Token": csrf_token},
            json={"display_name": "  Studio Admin  "},
        )
        assert updated.status_code == 200
        assert updated.json()["display_name"] == "Studio Admin"

        current = client.get("/api/v1/auth/me")
        assert current.status_code == 200
        assert current.json()["display_name"] == "Studio Admin"


def test_cors_allows_configured_origin_with_credentials_and_rejects_others(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    app = create_app(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cors.db'}",
        initialize_schema=True,
        jwt_secret=JWT_SECRET,
    )
    with TestClient(app) as client:
        allowed = client.options(
            "/api/v1/auth/csrf",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        rejected = client.options(
            "/api/v1/auth/csrf",
            headers={
                "Origin": "http://untrusted.example",
                "Access-Control-Request-Method": "GET",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert allowed.headers["access-control-allow-credentials"] == "true"
    assert rejected.status_code == 400


def test_workspace_invites_are_single_use_and_members_share_workspace(tmp_path):
    with _client(tmp_path) as owner_client:
        owner_csrf, owner_registration = _register(
            owner_client,
            email="owner@example.com",
            workspace_name="Shared workspace",
        )
        assert owner_registration.status_code == 201
        invite_response = owner_client.post(
            "/api/v1/workspace/invites",
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert invite_response.status_code == 201
        invite = invite_response.json()

        with _client(tmp_path) as member_client:
            member_csrf, member_registration = _register(
                member_client,
                email="member@example.com",
                invite_token=invite["token"],
            )
            assert member_registration.status_code == 201
            assert member_registration.json()["role"] == "member"
            assert (
                member_registration.json()["workspace_id"]
                == owner_registration.json()["workspace_id"]
            )
            assert member_client.get("/api/v1/servers").status_code == 200
            assert (
                member_client.post(
                    "/api/v1/workspace/invites",
                    headers={"X-CSRF-Token": member_csrf},
                ).status_code
                == 403
            )

        with _client(tmp_path) as replay_client:
            _, replay = _register(
                replay_client,
                email="replay@example.com",
                invite_token=invite["token"],
            )
            assert replay.status_code == 400

        members = owner_client.get("/api/v1/workspace/members")
        assert members.status_code == 200
        member = next(
            record for record in members.json() if record["email"] == "member@example.com"
        )
        removal = owner_client.delete(
            f"/api/v1/workspace/members/{member['user_id']}",
            headers={"X-CSRF-Token": owner_csrf},
        )
        assert removal.status_code == 204

        with _client(tmp_path) as removed_member:
            assert removed_member.get("/api/v1/servers").status_code == 401


def test_refresh_rotates_token_and_logout_revokes_access(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="Session workspace",
        )
        assert registered.status_code == 201
        old_access = client.cookies.get("studio_access")
        assert old_access is not None
        old_refresh = client.cookies.get("studio_refresh")
        old_claims = jwt.decode(
            old_access,
            options={"verify_signature": False, "verify_exp": False},
            algorithms=["HS256"],
        )
        legacy_access = jwt.encode(
            {
                **old_claims,
                "iss": "fastmcp-studio",
                "aud": "fastmcp-studio-api",
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        assert client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"studio_access={legacy_access}"},
        ).status_code == 401

        rotated = client.post(
            "/api/v1/auth/refresh",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert rotated.status_code == 200
        assert client.get("/api/v1/auth/me").status_code == 200
        rotated_refresh = client.cookies.get("studio_refresh")
        assert rotated_refresh != old_refresh

        replay = client.post(
            "/api/v1/auth/refresh",
            headers={
                "X-CSRF-Token": csrf_token,
                "Cookie": f"studio_refresh={old_refresh}; csrf_token={csrf_token}",
            },
        )
        assert replay.status_code == 401

        client.cookies.set("studio_refresh", rotated_refresh)
        logged_out = client.post(
            "/api/v1/auth/logout",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert logged_out.status_code == 204
        revoked_access = client.get(
            "/api/v1/auth/me",
            headers={"Cookie": f"studio_access={old_access}"},
        )
        assert revoked_access.status_code == 401


def test_protected_server_secret_assignment_and_detach(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="MCP workspace",
        )
        assert registered.status_code == 201
        created_secret = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Research client"},
        )
        assert created_secret.status_code == 201
        secret = created_secret.json()
        token = secret["value"]

        protected = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Protected server",
                "auth_mode": "protected",
                "secret_id": secret["id"],
            },
        )
        assert protected.status_code == 201, protected.text
        server = protected.json()
        assert server["auth_mode"] == "protected"
        assert server["secret_name"] == "Research client"

        secrets_list = client.get("/api/v1/secrets")
        assert secrets_list.status_code == 200
        assert token not in secrets_list.text
        assert server["secret_id"] == secret["id"]

        unauthorized = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert unauthorized.status_code == 401
        authorized = client.post(
            server["endpoint_path"],
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        )
        assert authorized.status_code == 200
        assert "mcp-session-id" not in authorized.headers

        duplicate_assignment = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Second protected server",
                "auth_mode": "protected",
                "secret_id": secret["id"],
            },
        )
        assert duplicate_assignment.status_code == 409

        replacement_secret = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Replacement client"},
        ).json()
        replaced = client.patch(
            f"/api/v1/servers/{server['id']}/security",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "auth_mode": "protected",
                "secret_id": replacement_secret["id"],
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["secret_id"] == replacement_secret["id"]
        old_token_rejected = client.post(
            server["endpoint_path"],
            headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"},
            json={"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {}},
        )
        new_token_accepted = client.post(
            server["endpoint_path"],
            headers={
                **MCP_HEADERS,
                "Authorization": f"Bearer {replacement_secret['value']}",
            },
            json={"jsonrpc": "2.0", "id": 4, "method": "initialize", "params": {}},
        )
        assert old_token_rejected.status_code == 401
        assert new_token_accepted.status_code == 200

        normal = client.patch(
            f"/api/v1/servers/{server['id']}/security",
            headers={"X-CSRF-Token": csrf_token},
            json={"auth_mode": "normal"},
        )
        assert normal.status_code == 200
        assert normal.json()["auth_mode"] == "normal"
        assert all(
            item["server_id"] is None for item in client.get("/api/v1/secrets").json()
        )

        normal_mcp = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 5, "method": "initialize", "params": {}},
        )
        assert normal_mcp.status_code == 200

        deleted = client.delete(
            f"/api/v1/secrets/{secret['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert deleted.status_code == 204


def test_assigned_secret_cannot_be_deleted(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="Protected workspace",
        )
        assert registered.status_code == 201
        secret = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Attached"},
        ).json()
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Protected",
                "auth_mode": "protected",
                "secret_id": secret["id"],
            },
        ).json()
        deleted = client.delete(
            f"/api/v1/secrets/{secret['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert deleted.status_code == 409

        replaced = client.patch(
            f"/api/v1/servers/{server['id']}/security",
            headers={"X-CSRF-Token": csrf_token},
            json={"auth_mode": "normal"},
        )
        assert replaced.status_code == 200


def test_server_details_update_edits_metadata_and_access_together(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="Server edit workspace",
        )
        assert registered.status_code == 201

        secret = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Editing client"},
        ).json()
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Original name", "description": "Original description"},
        ).json()

        updated = client.patch(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "  Updated name  ",
                "description": "  Updated description  ",
                "auth_mode": "protected",
                "secret_id": secret["id"],
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Updated name"
        assert updated.json()["description"] == "Updated description"
        assert updated.json()["auth_mode"] == "protected"
        assert updated.json()["secret_id"] == secret["id"]
        assert updated.json()["endpoint_path"] == server["endpoint_path"]

        unauthorized = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        authorized = client.post(
            server["endpoint_path"],
            headers={**MCP_HEADERS, "Authorization": f"Bearer {secret['value']}"},
            json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        )
        assert unauthorized.status_code == 401
        assert authorized.status_code == 200

        server_info = client.post(
            server["endpoint_path"],
            headers={**MCP_HEADERS, "Authorization": f"Bearer {secret['value']}"},
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "server_info", "arguments": {}},
            },
        )
        assert server_info.status_code == 200
        assert _mcp_result(server_info)["structuredContent"]["name"] == "Updated name"

        reverted = client.patch(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Updated name",
                "description": "",
                "auth_mode": "normal",
                "secret_id": None,
            },
        )
        assert reverted.status_code == 200, reverted.text
        assert reverted.json()["auth_mode"] == "normal"
        assert reverted.json()["secret_id"] is None
        assert reverted.json()["endpoint_path"] == server["endpoint_path"]
        assert all(
            item["server_id"] is None for item in client.get("/api/v1/secrets").json()
        )


def test_server_details_update_validates_fields_and_workspace_scope(tmp_path):
    database_path = tmp_path / "workspace.db"
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="Server edit workspace",
        )
        assert registered.status_code == 201
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Original name"},
        ).json()

        invalid_name = client.patch(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "   ",
                "description": "",
                "auth_mode": "normal",
                "secret_id": None,
            },
        )
        invalid_description = client.patch(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Valid name",
                "description": "x" * 301,
                "auth_mode": "normal",
                "secret_id": None,
            },
        )
        assert invalid_name.status_code == 422
        assert invalid_description.status_code == 422

        other_server_id = _seed_other_workspace(database_path, with_server=True)
        assert other_server_id is not None
        cross_workspace_update = client.patch(
            f"/api/v1/servers/{other_server_id}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Unauthorized edit",
                "description": "",
                "auth_mode": "normal",
                "secret_id": None,
            },
        )
        assert cross_workspace_update.status_code == 404

        current = client.get("/api/v1/servers").json()
        assert len(current) == 1
        assert current[0]["name"] == "Original name"


def test_secret_registry_pages_are_workspace_scoped_and_preserve_full_list(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, registered = _register(
            client,
            email="owner@example.com",
            workspace_name="Secrets workspace",
        )
        assert registered.status_code == 201

        empty_page = client.get("/api/v1/secrets/registry")
        assert empty_page.status_code == 200
        assert empty_page.json() == {
            "items": [],
            "page": 1,
            "page_size": 10,
            "total": 0,
            "total_pages": 0,
        }

        for index in range(11):
            created = client.post(
                "/api/v1/secrets",
                headers={"X-CSRF-Token": csrf_token},
                json={"name": f"Secret {index}"},
            )
            assert created.status_code == 201

        first_page = client.get("/api/v1/secrets/registry?page=1&page_size=10")
        second_page = client.get("/api/v1/secrets/registry?page=2&page_size=10")
        assert first_page.status_code == second_page.status_code == 200
        assert first_page.json()["total"] == 11
        assert first_page.json()["total_pages"] == 2
        assert first_page.json()["page"] == 1
        assert len(first_page.json()["items"]) == 10
        assert second_page.json()["page"] == 2
        assert len(second_page.json()["items"]) == 1
        assert not {
            item["id"] for item in first_page.json()["items"]
        } & {
            item["id"] for item in second_page.json()["items"]
        }
        assert client.get("/api/v1/secrets/registry?page=99").json()["page"] == 2
        assert client.get("/api/v1/secrets/registry?page=0").status_code == 422
        assert client.get("/api/v1/secrets/registry?page_size=11").status_code == 422
        assert len(client.get("/api/v1/secrets").json()) == 11

        _seed_other_workspace(tmp_path / "workspace.db", with_secret=True)
        scoped_page = client.get("/api/v1/secrets/registry")
        assert scoped_page.status_code == 200
        assert scoped_page.json()["total"] == 11


def test_member_registry_pages_and_clamps_after_removal(tmp_path):
    with _client(tmp_path) as owner_client:
        _, owner_registered = _register(
            owner_client,
            email="owner@example.com",
            workspace_name="Members workspace",
        )
        assert owner_registered.status_code == 201

        for index in range(10):
            invite_csrf = _csrf(owner_client)
            invite = owner_client.post(
                "/api/v1/workspace/invites",
                headers={"X-CSRF-Token": invite_csrf},
            )
            assert invite.status_code == 201
            with _client(tmp_path) as member_client:
                _, registered = _register(
                    member_client,
                    email=f"member-{index:02}@example.com",
                    invite_token=invite.json()["token"],
                )
                assert registered.status_code == 201

        _seed_other_workspace(tmp_path / "workspace.db")
        first_page = owner_client.get(
            "/api/v1/workspace/members/registry?page=1&page_size=10"
        )
        second_page = owner_client.get(
            "/api/v1/workspace/members/registry?page=2&page_size=10"
        )
        assert first_page.status_code == second_page.status_code == 200
        assert first_page.json()["total"] == 11
        assert first_page.json()["total_pages"] == 2
        assert len(first_page.json()["items"]) == 10
        assert second_page.json()["page"] == 2
        assert len(second_page.json()["items"]) == 1
        assert owner_client.get("/api/v1/workspace/members/registry?page=0").status_code == 422
        assert owner_client.get(
            "/api/v1/workspace/members/registry?page_size=11"
        ).status_code == 422
        assert len(owner_client.get("/api/v1/workspace/members").json()) == 11

        last_member = second_page.json()["items"][0]
        removal = owner_client.delete(
            f"/api/v1/workspace/members/{last_member['user_id']}",
            headers={"X-CSRF-Token": _csrf(owner_client)},
        )
        assert removal.status_code == 204
        stale_page = owner_client.get(
            "/api/v1/workspace/members/registry?page=2&page_size=10"
        )
        assert stale_page.status_code == 200
        assert stale_page.json()["page"] == 1
        assert stale_page.json()["total"] == 10
        assert stale_page.json()["total_pages"] == 1

        scoped_page = owner_client.get("/api/v1/workspace/members/registry")
        assert scoped_page.status_code == 200
        assert scoped_page.json()["total"] == 10
