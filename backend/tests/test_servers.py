import asyncio
import base64
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.main import create_app
from app.services import resources as resources_service
from app.models import (
    MCPPromptDefinition,
    MCPToolDefinition,
    ServerDefinition,
    ServerSecret,
    User,
    Workspace,
    WorkspaceMembership,
)
from app.resource_storage import ResourceStorageError
from app.security import hash_password


class InMemoryResourceStore:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def verify(self):
        return None

    def upload(self, object_key, content, size_bytes, mime_type, sha256):
        value = content.read()
        assert len(value) == size_bytes
        assert hashlib.sha256(value).hexdigest() == sha256
        self.objects[object_key] = value

    def download(self, object_key):
        return self.objects[object_key]

    def delete(self, object_key):
        self.objects.pop(object_key, None)


class FailingDeleteResourceStore(InMemoryResourceStore):
    def delete(self, object_key):
        raise ResourceStorageError("Could not delete the resource file.")


def _mcp_result(response):
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        body = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ")
        )
    return json.loads(body)["result"]


def _client(tmp_path, resource_object_store=None):
    database_path = tmp_path / "servers.db"
    return TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{database_path}",
            initialize_schema=True,
            jwt_secret="test-signing-key-that-is-at-least-32-bytes",
            resource_object_store=(
                resource_object_store
                if resource_object_store is not None
                else InMemoryResourceStore()
            ),
        )
    )


def _csrf(client):
    return client.get("/api/v1/auth/csrf").json()["csrf_token"]


def _register(client, *, email="owner@example.com", workspace="Test workspace", token=None):
    csrf_token = _csrf(client)
    response = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "email": email,
            "password": "secure-test-password-2026",
            "display_name": email.partition("@")[0],
            "workspace_name": workspace if token is None else None,
            "invite_token": token,
        },
    )
    assert response.status_code == 201, response.text
    return csrf_token, response.json()


def _login(client, *, email="owner@example.com"):
    csrf_token = _csrf(client)
    response = client.post(
        "/api/v1/auth/login",
        headers={"X-CSRF-Token": csrf_token},
        json={"email": email, "password": "secure-test-password-2026"},
    )
    assert response.status_code == 200, response.text
    return csrf_token


def _create_server(client, csrf_token, name="Weather"):
    return client.post(
        "/api/v1/servers",
        headers={"X-CSRF-Token": csrf_token},
        json={"name": name},
    )


def _seed_other_workspace_summary(database_path):
    async def seed():
        engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        now = datetime.now(timezone.utc)
        workspace_id = uuid4().hex
        server_id = uuid4().hex
        user_id = uuid4().hex
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
                        email="other@example.com",
                        display_name="Other member",
                        password_hash=hash_password("other-workspace-password"),
                        created_at=now,
                    ),
                    WorkspaceMembership(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        role="owner",
                        created_at=now,
                    ),
                    ServerDefinition(
                        id=server_id,
                        workspace_id=workspace_id,
                        name="Other server",
                        description="",
                        created_at=now,
                        endpoint_path=f"/mcp/{uuid4().hex}/",
                        auth_required=False,
                    ),
                    ServerSecret(
                        id=uuid4().hex,
                        workspace_id=workspace_id,
                        server_id=None,
                        name="Other workspace secret",
                        token_hash=uuid4().hex * 2,
                        created_at=now,
                    ),
                    MCPToolDefinition(
                        id=uuid4().hex,
                        workspace_id=workspace_id,
                        server_id=server_id,
                        name="other_tool",
                        source='def other_tool() -> str:\n    return "other"\n',
                        created_at=now,
                        updated_at=now,
                    ),
                    MCPPromptDefinition(
                        id=uuid4().hex,
                        workspace_id=workspace_id,
                        server_id=server_id,
                        name="other_prompt",
                        description="",
                        template="Other prompt.",
                        arguments=[],
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            await session.commit()
        await engine.dispose()
        return server_id

    return asyncio.run(seed())


def test_create_and_list_server(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        created = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "  Weather  ", "description": " Local forecast "},
        )

        assert created.status_code == 201
        record = created.json()
        assert record["name"] == "Weather"
        assert record["description"] == "Local forecast"
        assert record["endpoint_path"].startswith("/mcp/")
        assert record["endpoint_path"].endswith("/")
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        initialized = client.post(
            record["endpoint_path"],
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            },
        )
        assert initialized.status_code == 200
        assert "mcp-session-id" not in initialized.headers

        listed_tools = client.post(
            record["endpoint_path"],
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert listed_tools.status_code == 200
        assert _mcp_result(listed_tools)["tools"][0]["name"] == "server_info"

        called_tool = client.post(
            record["endpoint_path"],
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "server_info", "arguments": {}},
            },
        )
        assert called_tool.status_code == 200
        assert _mcp_result(called_tool)["structuredContent"] == {
            "id": record["id"],
            "name": record["name"],
        }
        assert client.get("/api/v1/servers").json() == [record]


def test_server_definitions_survive_backend_restart(tmp_path):
    with _client(tmp_path) as first_client:
        csrf_token, _ = _register(first_client)
        created = _create_server(first_client, csrf_token, "Persistent")
        assert created.status_code == 201

    with _client(tmp_path) as restarted_client:
        _login(restarted_client)
        listed = restarted_client.get("/api/v1/servers")
        assert listed.status_code == 200
        assert listed.json() == [created.json()]
        endpoint = created.json()["endpoint_path"]
        listed_tools = restarted_client.post(
            endpoint,
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert listed_tools.status_code == 200
        assert _mcp_result(listed_tools)["tools"][0]["name"] == "server_info"


def test_server_registry_pages_are_workspace_scoped_and_clamp_stale_pages(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        expected_names = []
        for index in range(12):
            name = f"Registry server {index:02}"
            response = _create_server(client, csrf_token, name)
            assert response.status_code == 201, response.text
            expected_names.append(name)

        first_page = client.get("/api/v1/servers/registry?page=1&page_size=10")
        assert first_page.status_code == 200, first_page.text
        first_page_data = first_page.json()
        assert {
            key: first_page_data[key]
            for key in ("page", "page_size", "total", "total_pages")
        } == {"page": 1, "page_size": 10, "total": 12, "total_pages": 2}
        assert [item["name"] for item in first_page_data["items"]] == expected_names[:10]

        for page_size in (25, 50):
            larger_page = client.get(
                f"/api/v1/servers/registry?page=1&page_size={page_size}"
            )
            assert larger_page.status_code == 200
            assert larger_page.json()["page_size"] == page_size
            assert [item["name"] for item in larger_page.json()["items"]] == expected_names

        second_page = client.get("/api/v1/servers/registry?page=2&page_size=10")
        assert [item["name"] for item in second_page.json()["items"]] == expected_names[10:]

        stale_page = client.get("/api/v1/servers/registry?page=99&page_size=10")
        assert stale_page.json()["page"] == 2
        assert [item["name"] for item in stale_page.json()["items"]] == expected_names[10:]

        assert client.get("/api/v1/servers/registry?page=0").status_code == 422
        assert client.get("/api/v1/servers/registry?page_size=20").status_code == 422

        other_workspace_path = tmp_path / "other-workspace"
        other_workspace_path.mkdir()
        with _client(other_workspace_path) as other_client:
            _register(other_client, email="other@example.com")
            empty_page = other_client.get("/api/v1/servers/registry")
            assert empty_page.status_code == 200
            assert empty_page.json() == {
                "items": [],
                "page": 1,
                "page_size": 10,
                "total": 0,
                "total_pages": 0,
            }


def test_rejects_blank_server_name(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        response = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "  "},
        )

    assert response.status_code == 422


def test_server_delete_removes_content_files_and_detaches_token(tmp_path):
    storage = InMemoryResourceStore()
    file_content = b"\x00server-resource"
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        secret_response = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Server token"},
        )
        assert secret_response.status_code == 201, secret_response.text
        secret = secret_response.json()
        server_response = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "Protected server",
                "auth_mode": "protected",
                "secret_id": secret["id"],
            },
        )
        assert server_response.status_code == 201, server_response.text
        server = server_response.json()

        tool = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "source": '''def deletion_tool() -> str:
    """Return a result for deletion tests."""
    return "ready"
'''
            },
        )
        assert tool.status_code == 201, tool.text
        prompt = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "deletion_prompt", "template": "Test deletion."},
        )
        assert prompt.status_code == 201, prompt.text
        resource = client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "uri": "docs://deletion-test",
                "name": "Deletion test",
                "content": "This resource should be removed.",
            },
        )
        assert resource.status_code == 201, resource.text
        binary_resource = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://deletion-test/sample.pdf",
                        "name": "Deletion test file",
                    }
                )
            },
            files={"file": ("sample.pdf", file_content, "application/pdf")},
        )
        assert binary_resource.status_code == 201, binary_resource.text
        assert len(storage.objects) == 1

        summary = client.get(
            f"/api/v1/servers/{server['id']}/deletion-summary"
        )
        assert summary.status_code == 200
        assert summary.json() == {
            "tool_count": 1,
            "prompt_count": 1,
            "resource_count": 2,
            "file_resource_count": 1,
        }

        deleted = client.delete(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )

        assert deleted.status_code == 200, deleted.text
        assert deleted.json() == {
            "file_cleanup_failures": 0,
            "runtime_shutdown_failed": False,
        }
        assert storage.objects == {}
        saved_tokens = client.get("/api/v1/secrets")
        assert saved_tokens.status_code == 200
        token_records = saved_tokens.json()
        assert len(token_records) == 1
        assert token_records[0]["id"] == secret["id"]
        assert token_records[0]["server_id"] is None
        assert client.get(
            f"/api/v1/servers/{server['id']}/deletion-summary"
        ).status_code == 404
        unavailable = client.post(
            server["endpoint_path"],
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        assert unavailable.status_code == 404


def test_server_delete_reports_resource_file_cleanup_failure(tmp_path):
    storage = FailingDeleteResourceStore()
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        file_response = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://deletion-test/retained.pdf",
                        "name": "Retained on cleanup failure",
                    }
                )
            },
            files={"file": ("retained.pdf", b"resource", "application/pdf")},
        )
        assert file_response.status_code == 201, file_response.text
        assert len(storage.objects) == 1

        deleted = client.delete(
            f"/api/v1/servers/{server['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )

        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["file_cleanup_failures"] == 1
        assert len(storage.objects) == 1
        assert client.get(
            f"/api/v1/servers/{server['id']}/resources"
        ).status_code == 404


def test_server_delete_endpoints_are_workspace_scoped(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        other_server_id = _seed_other_workspace_summary(tmp_path / "servers.db")

        summary = client.get(
            f"/api/v1/servers/{other_server_id}/deletion-summary"
        )
        deleted = client.delete(
            f"/api/v1/servers/{other_server_id}",
            headers={"X-CSRF-Token": csrf_token},
        )

        assert summary.status_code == 404
        assert deleted.status_code == 404


def test_workspace_summary_returns_scoped_capability_counts(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        empty_summary = client.get("/api/v1/workspace/summary")
        assert empty_summary.status_code == 200
        assert empty_summary.json() == {
            "server_count": 0,
            "tool_count": 0,
            "active_tool_count": 0,
            "prompt_count": 0,
            "secret_count": 0,
            "member_count": 1,
        }

        server = _create_server(client, csrf_token).json()
        created_secret = client.post(
            "/api/v1/secrets",
            headers={"X-CSRF-Token": csrf_token},
            json={"name": "Workspace secret"},
        )
        assert created_secret.status_code == 201, created_secret.text
        created_tool = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "source": '''def greet(name: str) -> str:
    """Greet a person."""
    return f"Hello, {name}"
'''
            },
        )
        assert created_tool.status_code == 201, created_tool.text
        created_prompt = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "greeting",
                "template": "Say hello.",
            },
        )
        assert created_prompt.status_code == 201, created_prompt.text
        _seed_other_workspace_summary(tmp_path / "servers.db")

        summary = client.get("/api/v1/workspace/summary")

        assert summary.status_code == 200
        assert summary.json() == {
            "server_count": 1,
            "tool_count": 1,
            "active_tool_count": int(created_tool.json()["execution_status"] == "active"),
            "prompt_count": 1,
            "secret_count": 1,
            "member_count": 1,
        }


def test_recent_servers_are_limited_to_five_and_workspace_scoped(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        created_servers = []
        for index in range(7):
            created = _create_server(client, csrf_token, name=f"Server {index + 1}")
            assert created.status_code == 201, created.text
            created_servers.append(created.json())

        _seed_other_workspace_summary(tmp_path / "servers.db")
        response = client.get("/api/v1/servers/recent")

        assert response.status_code == 200
        recent_servers = response.json()
        expected_servers = sorted(
            created_servers,
            key=lambda server: (server["created_at"], server["id"]),
            reverse=True,
        )[:5]
        assert [server["id"] for server in recent_servers] == [
            server["id"] for server in expected_servers
        ]
        assert len(recent_servers) == 5
        assert all(server["name"] != "Other server" for server in recent_servers)
        assert len(client.get("/api/v1/servers").json()) == 7


def test_tool_drafts_are_validated_persisted_and_not_published(tmp_path):
    source = '''from typing import Literal

def forecast(city: str, units: Literal["c", "f"] = "c") -> dict[str, str]:
    """Return a forecast for the requested city."""
    return {"city": city, "units": units}
'''
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        created = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={"source": source},
        )

        assert created.status_code == 201, created.text
        tool = created.json()
        assert tool["name"] == "forecast"
        assert tool["description"] == "Return a forecast for the requested city."
        assert tool["execution_status"] == "disabled"
        assert tool["input_schema"]["required"] == ["city"]
        assert tool["input_schema"]["properties"]["units"]["enum"] == ["c", "f"]

        listed = client.get(f"/api/v1/servers/{server['id']}/tools")
        assert listed.status_code == 200
        assert listed.json() == [tool]

        protocol_headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        listed_mcp_tools = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert listed_mcp_tools.status_code == 200
        assert [item["name"] for item in _mcp_result(listed_mcp_tools)["tools"]] == [
            "server_info"
        ]

        updated_source = '''def forecast(city: str) -> str:
    """Return a city-specific forecast message."""
    return city
'''
        updated = client.put(
            f"/api/v1/servers/{server['id']}/tools/{tool['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={"source": updated_source},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["description"] == "Return a city-specific forecast message."

        deleted = client.delete(
            f"/api/v1/servers/{server['id']}/tools/{tool['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/servers/{server['id']}/tools").json() == []


def test_prompt_templates_are_exposed_and_managed(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        request = {
            "name": "review_request",
            "description": "Create a code review request.",
            "template": "Review {{code}} in a {{style}} style; focus on {{focus}}.",
            "arguments": [
                {
                    "name": "code",
                    "description": "Source code to review.",
                    "required": True,
                },
                {
                    "name": "style",
                    "description": "Review tone.",
                    "required": False,
                    "default_value": "concise",
                },
                {
                    "name": "focus",
                    "description": "Review focus.",
                    "required": False,
                },
            ],
        }
        created = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json=request,
        )

        assert created.status_code == 201, created.text
        prompt = created.json()
        assert prompt["name"] == "review_request"
        assert prompt["arguments"][0]["required"] is True
        assert prompt["arguments"][1]["default_value"] == "concise"

        listed = client.get(f"/api/v1/servers/{server['id']}/prompts")
        assert listed.status_code == 200
        assert listed.json() == [prompt]

        protocol_headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        listed_mcp_prompts = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list"},
        )
        assert listed_mcp_prompts.status_code == 200
        mcp_prompt = _mcp_result(listed_mcp_prompts)["prompts"][0]
        assert mcp_prompt["name"] == "review_request"
        assert mcp_prompt["description"] == "Create a code review request."
        assert [(arg["name"], arg["required"]) for arg in mcp_prompt["arguments"]] == [
            ("code", True),
            ("style", False),
            ("focus", False),
        ]
        assert [
            arg["description"].startswith(expected)
            for arg, expected in zip(
                mcp_prompt["arguments"],
                ["Source code to review.", "Review tone.", "Review focus."],
                strict=True,
            )
        ] == [True, True, True]

        rendered = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "prompts/get",
                "params": {
                    "name": "review_request",
                    "arguments": {"code": "print('hello')"},
                },
            },
        )
        assert rendered.status_code == 200
        assert _mcp_result(rendered)["messages"][0]["content"]["text"] == (
            "Review print('hello') in a concise style; focus on ."
        )

        updated_request = {
            "name": "code_review",
            "description": "Review code for a requested concern.",
            "template": "Review {{code}} for {{focus}}.",
            "arguments": [
                {"name": "code", "required": True},
                {"name": "focus", "required": False},
            ],
        }
        updated = client.put(
            f"/api/v1/servers/{server['id']}/prompts/{prompt['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json=updated_request,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "code_review"

        after_update = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "prompts/list"},
        )
        assert [
            item["name"] for item in _mcp_result(after_update)["prompts"]
        ] == ["code_review"]

        deleted = client.delete(
            f"/api/v1/servers/{server['id']}/prompts/{prompt['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/servers/{server['id']}/prompts").json() == []

        after_delete = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 4, "method": "prompts/list"},
        )
        assert _mcp_result(after_delete)["prompts"] == []


def test_tool_and_prompt_lists_support_server_side_pagination(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        for index in range(13):
            tool = client.post(
                f"/api/v1/servers/{server['id']}/tools",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "source": (
                        f'def lookup_{index:02}() -> str:\n'
                        f'    """Lookup value {index}."""\n'
                        '    return "value"\n'
                    )
                },
            )
            assert tool.status_code == 201, tool.text
            prompt = client.post(
                f"/api/v1/servers/{server['id']}/prompts",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "name": f"prompt_{index:02}",
                    "template": f"Prompt template {index}.",
                },
            )
            assert prompt.status_code == 201, prompt.text

        tool_page = client.get(
            f"/api/v1/servers/{server['id']}/tools/page?page=1&page_size=10"
        )
        prompt_page = client.get(
            f"/api/v1/servers/{server['id']}/prompts/page?page=1&page_size=10"
        )
        assert tool_page.status_code == 200, tool_page.text
        assert prompt_page.status_code == 200, prompt_page.text
        assert (tool_page.json()["total"], tool_page.json()["total_pages"]) == (13, 2)
        assert (prompt_page.json()["total"], prompt_page.json()["total_pages"]) == (13, 2)
        assert len(tool_page.json()["items"]) == 10
        assert len(prompt_page.json()["items"]) == 10

        for page_size in (12, 25, 50):
            wider_tool_page = client.get(
                f"/api/v1/servers/{server['id']}/tools/page?page_size={page_size}"
            )
            wider_prompt_page = client.get(
                f"/api/v1/servers/{server['id']}/prompts/page?page_size={page_size}"
            )
            assert wider_tool_page.status_code == wider_prompt_page.status_code == 200
            assert wider_tool_page.json()["page_size"] == page_size
            assert wider_prompt_page.json()["page_size"] == page_size

        twelve_tool_page = client.get(
            f"/api/v1/servers/{server['id']}/tools/page?page=1&page_size=12"
        )
        twelve_prompt_page = client.get(
            f"/api/v1/servers/{server['id']}/prompts/page?page=1&page_size=12"
        )
        assert len(twelve_tool_page.json()["items"]) == 12
        assert len(twelve_prompt_page.json()["items"]) == 12

        tool_last_page = client.get(
            f"/api/v1/servers/{server['id']}/tools/page?page=99&page_size=12"
        )
        prompt_last_page = client.get(
            f"/api/v1/servers/{server['id']}/prompts/page?page=2&page_size=12"
        )
        assert tool_last_page.json()["page"] == prompt_last_page.json()["page"] == 2
        assert len(tool_last_page.json()["items"]) == 1
        assert len(prompt_last_page.json()["items"]) == 1

        assert (
            client.get(f"/api/v1/servers/{server['id']}/tools/page?page_size=20").status_code
            == 422
        )
        assert (
            client.get(f"/api/v1/servers/{server['id']}/prompts/page?page_size=20").status_code
            == 422
        )
        assert (
            client.get(f"/api/v1/servers/{server['id']}/prompts/page?page=0").status_code
            == 422
        )
        assert len(client.get(f"/api/v1/servers/{server['id']}/tools").json()) == 13
        assert len(client.get(f"/api/v1/servers/{server['id']}/prompts").json()) == 13

        other_workspace_path = tmp_path / "other-workspace"
        other_workspace_path.mkdir()
        with _client(other_workspace_path) as other_client:
            _register(other_client, email="other@example.com")
            assert (
                other_client.get(
                    f"/api/v1/servers/{server['id']}/tools/page"
                ).status_code
                == 404
            )
            assert (
                other_client.get(
                    f"/api/v1/servers/{server['id']}/prompts/page"
                ).status_code
                == 404
            )


def test_prompt_templates_are_validated_and_workspace_scoped(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        invalid = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "name": "invalid_template",
                "template": "Summarize {{topic}}.",
                "arguments": [],
            },
        )
        assert invalid.status_code == 422
        assert "Define prompt arguments" in invalid.json()["detail"][0]["msg"]

        request = {
            "name": "summarize",
            "template": "Summarize {{topic}}.",
            "arguments": [{"name": "topic", "required": True}],
        }
        created = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json=request,
        )
        assert created.status_code == 201, created.text

        duplicate = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json=request,
        )
        assert duplicate.status_code == 409

        other_workspace_path = tmp_path / "other-workspace"
        other_workspace_path.mkdir()
        with _client(other_workspace_path) as other_workspace_client:
            _register(other_workspace_client, email="other@example.com")
            hidden = other_workspace_client.get(
                f"/api/v1/servers/{server['id']}/prompts"
            )
            assert hidden.status_code == 404


def test_prompt_definitions_persist_across_backend_restart(tmp_path):
    request = {
        "name": "summarize",
        "description": "Summarize a topic.",
        "template": "Summarize {{topic}}.",
        "arguments": [{"name": "topic", "required": True}],
    }
    with _client(tmp_path) as first_client:
        csrf_token, _ = _register(first_client)
        server = _create_server(first_client, csrf_token).json()
        created = first_client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf_token},
            json=request,
        )
        assert created.status_code == 201, created.text

    with _client(tmp_path) as restarted_client:
        _login(restarted_client)
        restored = restarted_client.get(
            f"/api/v1/servers/{server['id']}/prompts"
        )
        assert restored.status_code == 200
        assert restored.json() == [created.json()]

        mcp_response = restarted_client.post(
            server["endpoint_path"],
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {
                    "name": "summarize",
                    "arguments": {"topic": "restored prompt"},
                },
            },
        )
        assert mcp_response.status_code == 200
        assert _mcp_result(mcp_response)["messages"][0]["content"]["text"] == (
            "Summarize restored prompt."
        )


def test_tool_definition_rejects_invalid_source(tmp_path):
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        response = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={"source": "print('not a function')"},
        )

    assert response.status_code == 422
    assert "one top-level function" in response.json()["detail"]


def test_tool_draft_persists_across_backend_restart(tmp_path):
    with _client(tmp_path) as first_client:
        csrf_token, _ = _register(first_client)
        server = _create_server(first_client, csrf_token).json()
        created = first_client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "source": '''def greet(name: str) -> str:
    """Create a greeting."""
    return f"Hello, {name}"
'''
            },
        )
        assert created.status_code == 201, created.text

    with _client(tmp_path) as restarted_client:
        _login(restarted_client)
        restored = restarted_client.get(f"/api/v1/servers/{server['id']}/tools")
        assert restored.status_code == 200
        assert restored.json() == [created.json()]


def test_tool_drafts_are_workspace_scoped(tmp_path):
    with _client(tmp_path) as owner_client:
        csrf_token, _ = _register(owner_client)
        server = _create_server(owner_client, csrf_token).json()
        created = owner_client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "source": '''def private_tool(value: int) -> int:
    """A private workspace tool."""
    return value
'''
            },
        )
        assert created.status_code == 201, created.text

        async def add_other_workspace() -> None:
            now = datetime.now(timezone.utc)
            workspace_id = str(uuid4())
            user_id = str(uuid4())
            async with owner_client.app.state.session_factory() as session:
                session.add(
                    Workspace(
                        id=workspace_id,
                        name="Another workspace",
                        bootstrap_key=uuid4().hex,
                        created_at=now,
                    )
                )
                session.add(
                    User(
                        id=user_id,
                        email="another-owner@example.com",
                        display_name="Another owner",
                        password_hash=hash_password("secure-test-password-2026"),
                        created_at=now,
                    )
                )
                session.add(
                    WorkspaceMembership(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        role="owner",
                        created_at=now,
                    )
                )
                await session.commit()

        asyncio.run(add_other_workspace())

    with _client(tmp_path) as other_client:
        _login(other_client, email="another-owner@example.com")
        other_csrf = _csrf(other_client)
        response = other_client.get(f"/api/v1/servers/{server['id']}/tools")
        assert response.status_code == 404
        denied_create = other_client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": other_csrf},
            json={"source": created.json()["source"]},
        )
        assert denied_create.status_code == 404


def test_concurrent_creates_are_all_persisted_once(tmp_path):
    number_of_servers = 12
    with _client(tmp_path) as client:
        csrf_token, _ = _register(client)
        with ThreadPoolExecutor(max_workers=number_of_servers * 2) as executor:
            create_futures = [
                executor.submit(
                    client.post,
                    "/api/v1/servers",
                    headers={"X-CSRF-Token": csrf_token},
                    json={"name": f"Concurrent server {index}"},
                )
                for index in range(number_of_servers)
            ]
            list_futures = [
                executor.submit(client.get, "/api/v1/servers")
                for _ in range(number_of_servers)
            ]
            responses = [future.result() for future in create_futures]
            list_responses = [future.result() for future in list_futures]

        assert all(response.status_code == 201 for response in responses)
        assert all(response.status_code == 200 for response in list_responses)
        assert all(isinstance(response.json(), list) for response in list_responses)
        created = [response.json() for response in responses]
        assert len({record["id"] for record in created}) == number_of_servers
        assert len({record["endpoint_path"] for record in created}) == number_of_servers

        listed = client.get("/api/v1/servers")
        assert listed.status_code == 200
        assert len(listed.json()) == number_of_servers
        assert {record["id"] for record in listed.json()} == {
            record["id"] for record in created
        }

    with _client(tmp_path) as restarted_client:
        _login(restarted_client)
        persisted = restarted_client.get("/api/v1/servers").json()
        assert len(persisted) == number_of_servers
        assert {record["id"] for record in persisted} == {
            record["id"] for record in created
        }


def test_resource_definitions_are_published_managed_and_restored(tmp_path):
    protocol_headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with _client(tmp_path) as first_client:
        csrf_token, _ = _register(first_client)
        server = _create_server(first_client, csrf_token).json()
        static = first_client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "uri": "docs://handbook",
                "name": "Handbook",
                "content": "Welcome to the handbook.",
            },
        )
        assert static.status_code == 201, static.text
        assert static.json()["description"] == ""

        template = first_client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "uri": "catalog://items/{item_id}",
                "name": "Catalog item",
                "description": "Look up a catalog item.",
                "mime_type": "text/plain",
                "content": "Item {{item_id}}.",
            },
        )
        assert template.status_code == 201, template.text
        template_record = template.json()

        page = first_client.get(
            f"/api/v1/servers/{server['id']}/resources/page?page=1&page_size=10"
        )
        assert page.status_code == 200
        assert page.json()["total"] == 2
        assert [item["id"] for item in page.json()["items"]] == [
            static.json()["id"],
            template_record["id"],
        ]

        listed = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        )
        assert listed.status_code == 200, listed.text
        assert [
            item["uri"] for item in _mcp_result(listed)["resources"]
        ] == ["docs://handbook"]

        listed_templates = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/templates/list",
            },
        )
        assert listed_templates.status_code == 200, listed_templates.text
        resource_template = _mcp_result(listed_templates)["resourceTemplates"][0]
        assert resource_template["uriTemplate"] == "catalog://items/{item_id}"

        static_read = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "resources/read",
                "params": {"uri": "docs://handbook"},
            },
        )
        assert static_read.status_code == 200, static_read.text
        assert _mcp_result(static_read)["contents"][0]["text"] == (
            "Welcome to the handbook."
        )

        template_read = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": "catalog://items/42"},
            },
        )
        assert template_read.status_code == 200, template_read.text
        assert _mcp_result(template_read)["contents"][0]["text"] == "Item 42."

        updated = first_client.put(
            f"/api/v1/servers/{server['id']}/resources/{template_record['id']}",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "uri": "catalog://records/{record_id}",
                "name": "Catalog record",
                "content": "Record {{record_id}}.",
            },
        )
        assert updated.status_code == 200, updated.text

        updated_read = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 5,
                "method": "resources/read",
                "params": {"uri": "catalog://records/r-7"},
            },
        )
        assert updated_read.status_code == 200, updated_read.text
        assert _mcp_result(updated_read)["contents"][0]["text"] == "Record r-7."

        deleted = first_client.delete(
            f"/api/v1/servers/{server['id']}/resources/{static.json()['id']}",
            headers={"X-CSRF-Token": csrf_token},
        )
        assert deleted.status_code == 204
        after_delete = first_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 6, "method": "resources/list"},
        )
        assert _mcp_result(after_delete)["resources"] == []

    with _client(tmp_path) as restarted_client:
        _login(restarted_client)
        restored = restarted_client.get(
            f"/api/v1/servers/{server['id']}/resources"
        )
        assert restored.status_code == 200
        assert [item["uri"] for item in restored.json()] == [
            "catalog://records/{record_id}"
        ]

        restored_read = restarted_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "catalog://records/r-8"},
            },
        )
        assert restored_read.status_code == 200, restored_read.text
        assert _mcp_result(restored_read)["contents"][0]["text"] == "Record r-8."


def test_binary_resource_upload_replace_read_restore_and_delete(tmp_path):
    protocol_headers = {
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-03-26",
    }
    storage = InMemoryResourceStore()
    file_bytes = b"\x00\x01resource-file-v1"
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        created = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://reference/sample.pdf",
                        "name": "Sample file",
                        "description": "A binary MCP resource.",
                        "mime_type": "application/pdf",
                        "audience": ["user"],
                        "priority": 0.7,
                    }
                )
            },
            files={"file": ("sample.pdf", file_bytes, "application/pdf")},
        )
        assert created.status_code == 201, created.text
        resource = created.json()
        assert resource["content_kind"] == "binary"
        assert resource["content"] is None
        assert resource["file_name"] == "sample.pdf"
        assert resource["mime_type"] == "application/pdf"
        assert resource["size_bytes"] == len(file_bytes)
        assert resource["sha256"] == hashlib.sha256(file_bytes).hexdigest()
        assert resource["audience"] == ["user"]
        assert resource["priority"] == 0.7
        assert len(storage.objects) == 1

        duplicate = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://reference/sample.pdf",
                        "name": "Duplicate file",
                    }
                )
            },
            files={"file": ("duplicate.pdf", b"duplicate", "application/pdf")},
        )
        assert duplicate.status_code == 409
        assert list(storage.objects.values()) == [file_bytes]

        listed = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
        )
        resource_listing = _mcp_result(listed)["resources"][0]
        assert resource_listing["annotations"]["audience"] == ["user"]
        assert resource_listing["annotations"]["priority"] == 0.7
        assert "lastModified" in resource_listing["annotations"]

        read = client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": resource["uri"]},
            },
        )
        contents = _mcp_result(read)["contents"][0]
        assert base64.b64decode(contents["blob"]) == file_bytes
        assert contents["mimeType"] == "application/pdf"

        replacement_bytes = b"\x02resource-file-v2"
        updated = client.put(
            f"/api/v1/servers/{server['id']}/resources/{resource['id']}/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": resource["uri"],
                        "name": resource["name"],
                        "description": resource["description"],
                        "mime_type": "application/pdf",
                        "audience": ["assistant"],
                        "priority": 0.2,
                    }
                )
            },
            files={"file": ("replacement.pdf", replacement_bytes, "application/pdf")},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["file_name"] == "replacement.pdf"
        assert list(storage.objects.values()) == [replacement_bytes]

    with _client(tmp_path, storage) as restarted_client:
        _login(restarted_client)
        restored_read = restarted_client.post(
            server["endpoint_path"],
            headers=protocol_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "resources/read",
                "params": {"uri": resource["uri"]},
            },
        )
        assert restored_read.status_code == 200, restored_read.text
        assert base64.b64decode(
            _mcp_result(restored_read)["contents"][0]["blob"]
        ) == replacement_bytes

        deleted = restarted_client.delete(
            f"/api/v1/servers/{server['id']}/resources/{resource['id']}",
            headers={"X-CSRF-Token": _csrf(restarted_client)},
        )
        assert deleted.status_code == 204
        assert storage.objects == {}


def test_binary_resource_upload_rejects_oversize_and_templates(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(resources_service, "MAX_RESOURCE_UPLOAD_BYTES", 4)
    storage = InMemoryResourceStore()
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        oversized = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {                    "uri": "files://reference/large.pdf", "name": "Large"}
                )
            },
            files={"file": ("large.pdf", b"12345", "application/pdf")},
        )
        assert oversized.status_code == 413
        assert storage.objects == {}

        templated = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://reference/{name}",
                        "name": "Templated binary",
                    }
                )
            },
            files={"file": ("small.pdf", b"123", "application/pdf")},
        )
        assert templated.status_code == 422
        assert storage.objects == {}


def test_binary_resource_upload_validates_mime_and_extension(tmp_path):
    storage = InMemoryResourceStore()
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        endpoint = f"/api/v1/servers/{server['id']}/resources/binary"

        def upload(file_name, mime_type, reported_mime_type, uri):
            metadata = {"uri": uri, "name": "Resource"}
            if mime_type is not None:
                metadata["mime_type"] = mime_type
            return client.post(
                endpoint,
                headers={"X-CSRF-Token": csrf_token},
                data={"metadata": json.dumps(metadata)},
                files={"file": (file_name, b"file data", reported_mime_type)},
            )

        unsupported = upload(
            "payload.exe", None, "application/octet-stream", "files://types/unsupported"
        )
        assert unsupported.status_code == 422
        assert storage.objects == {}

        disallowed_generic = upload(
            "payload.pdf",
            "application/octet-stream",
            "application/octet-stream",
            "files://types/generic",
        )
        assert disallowed_generic.status_code == 422
        assert storage.objects == {}

        extension_mismatch = upload(
            "payload.png", "application/pdf", "application/pdf", "files://types/extension"
        )
        assert extension_mismatch.status_code == 422
        assert storage.objects == {}

        reported_type_mismatch = upload(
            "payload.pdf", "application/pdf", "image/png", "files://types/reported"
        )
        assert reported_type_mismatch.status_code == 422
        assert storage.objects == {}

        accepted = upload(
            "payload.pdf", None, "application/pdf", "files://types/accepted"
        )
        assert accepted.status_code == 201, accepted.text
        assert accepted.json()["mime_type"] == "application/pdf"
        assert len(storage.objects) == 1


def test_binary_metadata_only_update_preserves_legacy_mime_type(tmp_path):
    storage = InMemoryResourceStore()
    with _client(tmp_path, storage) as client:
        csrf_token, _ = _register(client)
        server = _create_server(client, csrf_token).json()
        created = client.post(
            f"/api/v1/servers/{server['id']}/resources/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": "files://legacy/reference.pdf",
                        "name": "Legacy file",
                        "mime_type": "application/pdf",
                    }
                )
            },
            files={"file": ("reference.pdf", b"legacy bytes", "application/pdf")},
        )
        assert created.status_code == 201, created.text
        resource = created.json()

        with sqlite3.connect(tmp_path / "servers.db") as connection:
            result = connection.execute(
                "UPDATE mcp_resources SET mime_type = ? WHERE id = ?",
                ("application/octet-stream", resource["id"]),
            )
            assert result.rowcount == 1

        updated = client.put(
            f"/api/v1/servers/{server['id']}/resources/{resource['id']}/binary",
            headers={"X-CSRF-Token": csrf_token},
            data={
                "metadata": json.dumps(
                    {
                        "uri": resource["uri"],
                        "name": "Legacy file renamed",
                        "description": "Metadata-only update.",
                        "mime_type": None,
                    }
                )
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["mime_type"] == "application/octet-stream"
        assert len(storage.objects) == 1


def test_resource_definitions_are_workspace_scoped_and_validated(tmp_path):
    with _client(tmp_path) as owner_client:
        csrf_token, _ = _register(owner_client)
        server = _create_server(owner_client, csrf_token).json()
        invalid = owner_client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf_token},
            json={
                "uri": "docs://items/{item_id}",
                "name": "Invalid template",
                "content": "No matching placeholder.",
            },
        )
        assert invalid.status_code == 422

        async def add_other_workspace() -> None:
            now = datetime.now(timezone.utc)
            workspace_id = str(uuid4())
            user_id = str(uuid4())
            async with owner_client.app.state.session_factory() as session:
                session.add(
                    Workspace(
                        id=workspace_id,
                        name="Another resource workspace",
                        bootstrap_key=uuid4().hex,
                        created_at=now,
                    )
                )
                session.add(
                    User(
                        id=user_id,
                        email="resource-other@example.com",
                        display_name="Other owner",
                        password_hash=hash_password("secure-test-password-2026"),
                        created_at=now,
                    )
                )
                session.add(
                    WorkspaceMembership(
                        user_id=user_id,
                        workspace_id=workspace_id,
                        role="owner",
                        created_at=now,
                    )
                )
                await session.commit()

        asyncio.run(add_other_workspace())

    with _client(tmp_path) as other_client:
        _login(other_client, email="resource-other@example.com")
        denied = other_client.get(
            f"/api/v1/servers/{server['id']}/resources"
        )
        assert denied.status_code == 404
