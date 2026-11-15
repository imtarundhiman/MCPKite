import json
from typing import Any

from fastapi.testclient import TestClient

from app.main import create_app
from app.tool_executor import ToolExecutionError


class EchoToolExecutor:
    enabled = True

    async def execute(self, source, function_name, arguments, environment):
        if function_name == "fail":
            raise ToolExecutionError("Sandbox runner is unavailable.")
        if function_name == "get_config":
            return environment
        return {"function": function_name, "arguments": arguments}


def _mcp_result(response):
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        body = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ")
        )
    return json.loads(body)["result"]


def test_active_tool_is_published_invoked_updated_and_removed(tmp_path):
    database_path = tmp_path / "active-tools.db"
    with TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{database_path}",
            initialize_schema=True,
            jwt_secret="test-signing-key-that-is-at-least-32-bytes",
        )
    ) as client:
        client.app.state.tool_executor = EchoToolExecutor()
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        registered = client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf},
            json={
                "email": "tool-owner@example.com",
                "password": "secure-test-password-2026",
                "display_name": "Tool owner",
                "workspace_name": "Tool tests",
            },
        )
        assert registered.status_code == 201, registered.text
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Active tools"},
        ).json()
        source = '''from typing import Any

def greet(name: str, excited: bool = False) -> dict[str, Any]:
    """Return a greeting using the supplied options."""
    return {"greeting": name, "excited": excited}
'''
        created = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf},
            json={"source": source},
        )
        assert created.status_code == 201, created.text
        assert created.json()["execution_status"] == "active"

        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-03-26",
        }
        listed = client.post(
            server["endpoint_path"],
            headers=headers,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        tools = _mcp_result(listed)["tools"]
        assert {tool["name"] for tool in tools} == {"server_info", "greet"}
        greet_schema = next(tool for tool in tools if tool["name"] == "greet")["inputSchema"]
        assert greet_schema["required"] == ["name"]
        assert greet_schema["properties"]["excited"]["type"] == "boolean"

        called = client.post(
            server["endpoint_path"],
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "greet",
                    "arguments": {"name": "Ada", "excited": True},
                },
            },
        )
        assert called.status_code == 200
        assert _mcp_result(called)["structuredContent"] == {
            "function": "greet",
            "arguments": {"name": "Ada", "excited": True},
        }

        updated_source = '''def greet(name: str) -> str:
    """Return a plain greeting."""
    return name
'''
        updated = client.put(
            f"/api/v1/servers/{server['id']}/tools/{created.json()['id']}",
            headers={"X-CSRF-Token": csrf},
            json={"source": updated_source},
        )
        assert updated.status_code == 200, updated.text

        deleted = client.delete(
            f"/api/v1/servers/{server['id']}/tools/{created.json()['id']}",
            headers={"X-CSRF-Token": csrf},
        )
        assert deleted.status_code == 204
        after_delete = client.post(
            server["endpoint_path"],
            headers=headers,
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
        )
        assert [tool["name"] for tool in _mcp_result(after_delete)["tools"]] == [
            "server_info"
        ]
