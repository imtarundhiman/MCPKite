import base64
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


pytestmark = pytest.mark.skipif(
    os.getenv("TOOL_RUNNER_INTEGRATION") != "1",
    reason="Requires the Docker Compose sandbox runner.",
)
WORKSPACE_SECRET_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode(
    "ascii"
)


def _mcp_result(response):
    body = response.text
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        body = next(
            line.removeprefix("data: ")
            for line in body.splitlines()
            if line.startswith("data: ")
        )
    return json.loads(body)["result"]


def test_sandbox_allows_public_egress_and_blocks_internal_destinations(tmp_path):
    with TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sandbox.db'}",
            initialize_schema=True,
            jwt_secret="test-signing-key-that-is-at-least-32-bytes",
        )
    ) as client:
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        registered = client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf},
            json={
                "email": "sandbox-owner@example.com",
                "password": "secure-test-password-2026",
                "display_name": "Sandbox owner",
                "workspace_name": "Sandbox tests",
            },
        )
        assert registered.status_code == 201, registered.text
        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Sandbox egress"},
        ).json()
        simple_source = '''def double(value: int) -> int:
    """Double the integer input."""
    return value * 2
'''
        simple_tool = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf},
            json={"source": simple_source},
        )
        assert simple_tool.status_code == 201, simple_tool.text
        simple_call = client.post(
            server["endpoint_path"],
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "double", "arguments": {"value": 21}},
            },
        )
        assert simple_call.status_code == 200
        assert _mcp_result(simple_call)["structuredContent"] == {"result": 42}

        source = '''import socket
from urllib.request import urlopen

def check_network(public_url: str, internal_url: str) -> dict[str, bool | str | None]:
    """Check that public HTTP works and internal destinations are blocked."""
    try:
        with urlopen(public_url, timeout=3) as response:
            public_works = response.status == 200
        public_error = None
    except Exception as exc:
        public_works = False
        public_error = f"{type(exc).__name__}: {exc}"

    try:
        with urlopen(internal_url, timeout=2):
            internal_http_works = True
    except Exception:
        internal_http_works = False

    try:
        with socket.create_connection(("host.docker.internal", 8000), timeout=0.5):
            direct_host_works = True
    except OSError:
        direct_host_works = False

    try:
        with socket.create_connection(("tool-runner", 8001), timeout=0.5):
            direct_runner_works = True
    except OSError:
        direct_runner_works = False

    return {
        "public_works": public_works,
        "public_error": public_error,
        "internal_http_works": internal_http_works,
        "direct_host_works": direct_host_works,
        "direct_runner_works": direct_runner_works,
    }
'''
        created = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf},
            json={"source": source},
        )
        assert created.status_code == 201, created.text

        response = client.post(
            server["endpoint_path"],
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "check_network",
                    "arguments": {
                        "public_url": "https://example.com/",
                        "internal_url": "http://host.docker.internal:8000/health",
                    },
                },
            },
        )
        assert response.status_code == 200
        result = _mcp_result(response)
        assert result["structuredContent"] == {
            "public_works": True,
            "public_error": None,
            "internal_http_works": False,
            "direct_host_works": False,
            "direct_runner_works": False,
        }


def test_sandbox_tool_can_read_workspace_secret_from_environment(tmp_path):
    with TestClient(
        create_app(
            database_url=f"sqlite+aiosqlite:///{tmp_path / 'sandbox-config.db'}",
            initialize_schema=True,
            jwt_secret="test-signing-key-that-is-at-least-32-bytes",
            workspace_secret_key=WORKSPACE_SECRET_KEY,
        )
    ) as client:
        csrf = client.get("/api/v1/auth/csrf").json()["csrf_token"]
        registered = client.post(
            "/api/v1/auth/register",
            headers={"X-CSRF-Token": csrf},
            json={
                "email": "sandbox-config-owner@example.com",
                "password": "secure-test-password-2026",
                "display_name": "Sandbox config owner",
                "workspace_name": "Sandbox config tests",
            },
        )
        assert registered.status_code == 201, registered.text
        saved = client.post(
            "/api/v1/config-values",
            headers={"X-CSRF-Token": csrf},
            json={
                "name": "OPENAI_API_KEY",
                "kind": "secret",
                "value": "sk-sandbox-integration",
            },
        )
        assert saved.status_code == 201, saved.text

        server = client.post(
            "/api/v1/servers",
            headers={"X-CSRF-Token": csrf},
            json={"name": "Sandbox configuration"},
        ).json()
        tool = client.post(
            f"/api/v1/servers/{server['id']}/tools",
            headers={"X-CSRF-Token": csrf},
            json={
                "source": (
                    "import os\n\n"
                    "def read_key() -> dict[str, str]:\n"
                    '    """Read the workspace API key."""\n'
                    '    return {"value": os.environ["OPENAI_API_KEY"]}\n'
                )
            },
        )
        assert tool.status_code == 201, tool.text

        response = client.post(
            server["endpoint_path"],
            headers={
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-03-26",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "read_key", "arguments": {}},
            },
        )
        assert response.status_code == 200
        assert _mcp_result(response)["structuredContent"] == {
            "value": "sk-sandbox-integration"
        }
