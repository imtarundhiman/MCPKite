import base64
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app

JWT_SECRET = "test-signing-key-that-is-at-least-32-bytes"
PASSWORD = "secure-test-password-2026"
SECRET_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode("ascii")
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "MCP-Protocol-Version": "2025-03-26",
}


class ConfigCaptureExecutor:
    enabled = True

    async def execute(self, source, function_name, arguments, environment):
        return environment


def _client(database_path: Path) -> TestClient:
    return TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{database_path}",
            initialize_schema=True,
            jwt_secret=JWT_SECRET,
            workspace_secret_key=SECRET_KEY,
        )
    )


def _register(client: TestClient) -> str:
    csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    response = client.post(
        "/api/v1/auth/register",
        headers={"X-CSRF-Token": csrf},
        json={
            "email": "config-owner@example.com",
            "password": PASSWORD,
            "display_name": "Config owner",
            "workspace_name": "Config workspace",
        },
    )
    assert response.status_code == 201, response.text
    return csrf


def _mcp_result(response):
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        body = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ")
        )
    return json.loads(body)["result"]


def _save_value(client, csrf, name, kind, value):
    return client.post(
        "/api/v1/config-values",
        headers={"X-CSRF-Token": csrf},
        json={"name": name, "kind": kind, "value": value},
    )


def test_workspace_config_secrets_are_encrypted_and_never_returned(tmp_path):
    database_path = tmp_path / "workspace-config.db"
    with _client(database_path) as client:
        csrf = _register(client)
        variable = _save_value(
            client,
            csrf,
            "OPENAI_BASE_URL",
            "variable",
            "https://api.openai.com/v1",
        )
        secret = _save_value(
            client,
            csrf,
            "OPENAI_API_KEY",
            "secret",
            "sk-test-sensitive-value",
        )

        assert variable.status_code == 201, variable.text
        assert variable.json()["value"] == "https://api.openai.com/v1"
        assert secret.status_code == 201, secret.text
        assert secret.json()["value"] is None
        assert "sk-test-sensitive-value" not in secret.text

        listed = client.get("/api/v1/config-values")
        assert listed.status_code == 200
        records = {record["name"]: record for record in listed.json()}
        assert records["OPENAI_BASE_URL"]["value"] == "https://api.openai.com/v1"
        assert records["OPENAI_API_KEY"]["value"] is None

        with sqlite3.connect(database_path) as connection:
            stored_value, encrypted_value = connection.execute(
                "SELECT value, encrypted_value FROM workspace_config_values "
                "WHERE name = ?",
                ("OPENAI_API_KEY",),
            ).fetchone()
        assert stored_value is None
        assert encrypted_value != "sk-test-sensitive-value"

        replaced = client.put(
            f"/api/v1/config-values/{records['OPENAI_API_KEY']['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "OPENAI_API_KEY",
                "kind": "secret",
                "value": "sk-test-replacement",
            },
        )
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["value"] is None
        assert "sk-test-replacement" not in replaced.text


def test_workspace_config_registry_is_paginated_and_workspace_scoped(tmp_path):
    database_path = tmp_path / "workspace-config-pages.db"
    with _client(database_path) as client:
        csrf = _register(client)
        expected_names = [f"CONFIG_VALUE_{index:02d}" for index in range(12)]
        for index, name in enumerate(expected_names):
            response = _save_value(
                client,
                csrf,
                name,
                "secret" if index == 11 else "variable",
                f"config-value-{index}",
            )
            assert response.status_code == 201, response.text

        other_workspace_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO workspaces (id, name, bootstrap_key, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    other_workspace_id,
                    "Other workspace",
                    uuid4().hex,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO workspace_config_values "
                "(id, workspace_id, name, kind, value, encrypted_value, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    other_workspace_id,
                    "OTHER_WORKSPACE_ONLY",
                    "variable",
                    "must-not-leak",
                    None,
                    now,
                    now,
                ),
            )

        first_page = client.get(
            "/api/v1/config-values/registry?page=1&page_size=10"
        )
        assert first_page.status_code == 200, first_page.text
        assert first_page.json()["total"] == 12
        assert first_page.json()["total_pages"] == 2
        assert [item["name"] for item in first_page.json()["items"]] == expected_names[:10]
        assert "OTHER_WORKSPACE_ONLY" not in first_page.text

        last_page = client.get(
            "/api/v1/config-values/registry?page=2&page_size=10"
        )
        assert last_page.status_code == 200, last_page.text
        assert last_page.json()["page"] == 2
        assert [item["name"] for item in last_page.json()["items"]] == expected_names[10:]
        assert last_page.json()["items"][-1]["value"] is None
        assert "config-value-11" not in last_page.text

        clamped_page = client.get(
            "/api/v1/config-values/registry?page=99&page_size=10"
        )
        assert clamped_page.status_code == 200, clamped_page.text
        assert clamped_page.json()["page"] == 2

        invalid_page_size = client.get(
            "/api/v1/config-values/registry?page=1&page_size=11"
        )
        assert invalid_page_size.status_code == 422


def test_secret_validation_errors_do_not_echo_submitted_value(tmp_path):
    with _client(tmp_path / "workspace-config-validation.db") as client:
        csrf = _register(client)
        marker = "sensitive-validation-marker"
        response = _save_value(
            client,
            csrf,
            "TOO_LONG_SECRET",
            "secret",
            marker + ("x" * 10_000),
        )
        assert response.status_code == 422
        assert marker not in response.text


def test_saving_a_secret_requires_the_deployment_key(tmp_path):
    with TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'workspace-config-no-key.db'}",
            initialize_schema=True,
            jwt_secret=JWT_SECRET,
            workspace_secret_key="",
        )
    ) as client:
        csrf = _register(client)
        response = _save_value(
            client,
            csrf,
            "OPENAI_API_KEY",
            "secret",
            "sk-test-key",
        )
        assert response.status_code == 503
        assert response.json()["detail"] == (
            "WORKSPACE_SECRET_ENCRYPTION_KEY must be configured to save secrets."
        )


def test_workspace_values_resolve_in_prompts_resources_and_tool_calls(tmp_path):
    database_path = tmp_path / "workspace-config-runtime.db"
    with _client(database_path) as client:
        csrf = _register(client)
        assert _save_value(
            client,
            csrf,
            "OPENAI_BASE_URL",
            "variable",
            "https://api.openai.com/v1",
        ).status_code == 201
        other_workspace_id = str(uuid4())
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "INSERT INTO workspaces (id, name, bootstrap_key, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    other_workspace_id,
                    "Other workspace",
                    uuid4().hex,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.execute(
                "INSERT INTO workspace_config_values "
                "(id, workspace_id, name, kind, value, encrypted_value, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid4()),
                    other_workspace_id,
                    "OTHER_WORKSPACE_ONLY",
                    "variable",
                    "must-not-leak",
                    None,
                    datetime.now(timezone.utc).isoformat(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        assert _save_value(
            client,
            csrf,
            "OPENAI_API_KEY",
            "secret",
            "sk-runtime-secret",
        ).status_code == 201

        client.app.state.tool_executor = ConfigCaptureExecutor()
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Configured server"},
        ).json()
        prompt = client.post(
            f"/api/v1/servers/{server['id']}/prompts",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "call_openai",
                "template": (
                    "Send {{message}} to ${OPENAI_BASE_URL} with ${OPENAI_API_KEY}."
                ),
                "arguments": [{"name": "message", "required": True}],
            },
        )
        assert prompt.status_code == 201, prompt.text
        resource = client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf},
            json={
                "uri": "config://openai",
                "name": "OpenAI configuration",
                "content": "${OPENAI_BASE_URL}|${OPENAI_API_KEY}",
            },
        )
        assert resource.status_code == 201, resource.text
        tool = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf},
            json={
                "source": (
                    "def get_config() -> dict[str, str]:\n"
                    '    """Read workspace configuration."""\n'
                    "    return {}\n"
                )
            },
        )
        assert tool.status_code == 201, tool.text

        rendered_prompt = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "prompts/get",
                "params": {
                    "name": "call_openai",
                    "arguments": {"message": "summarize this"},
                },
            },
        )
        assert _mcp_result(rendered_prompt)["messages"][0]["content"]["text"] == (
            "Send summarize this to https://api.openai.com/v1 with sk-runtime-secret."
        )

        read_resource = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/read",
                "params": {"uri": "config://openai"},
            },
        )
        assert _mcp_result(read_resource)["contents"][0]["text"] == (
            "https://api.openai.com/v1|sk-runtime-secret"
        )

        call_tool = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "get_config", "arguments": {}},
            },
        )
        tool_result = _mcp_result(call_tool)
        assert tool_result["structuredContent"] == {
            "OPENAI_BASE_URL": "https://api.openai.com/v1",
            "OPENAI_API_KEY": "sk-runtime-secret",
        }
        assert "OTHER_WORKSPACE_ONLY" not in tool_result["structuredContent"]

        config_records = {
            item["name"]: item for item in client.get("/api/v1/config-values").json()
        }
        updated = client.put(
            f"/api/v1/config-values/{config_records['OPENAI_API_KEY']['id']}",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "OPENAI_API_KEY",
                "kind": "secret",
                "value": "sk-live-update",
            },
        )
        assert updated.status_code == 200, updated.text

        after_update = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": "config://openai"},
            },
        )
        assert _mcp_result(after_update)["contents"][0]["text"].endswith(
            "|sk-live-update"
        )


def test_missing_workspace_value_fails_when_an_artifact_is_used(tmp_path):
    with _client(tmp_path / "workspace-config-missing.db") as client:
        csrf = _register(client)
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Missing config server"},
        ).json()
        created = client.post(
            f"/api/v1/servers/{server['id']}/resources",
            headers={"X-CSRF-Token": csrf},
            json={
                "uri": "config://missing",
                "name": "Missing config",
                "content": "${UNDEFINED_VALUE}",
            },
        )
        assert created.status_code == 201, created.text

        response = client.post(
            server["endpoint_path"],
            headers=MCP_HEADERS,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "resources/read",
                "params": {"uri": "config://missing"},
            },
        )
        payload = json.loads(response.text.split("data: ", 1)[1])
        assert payload["error"]["message"] == (
            "Workspace value 'UNDEFINED_VALUE' is not defined."
        )
