import json
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from app.sandbox_limits import SandboxLimits


class ToolExecutionError(Exception):
    pass


class ToolExecutor(Protocol):
    @property
    def enabled(self) -> bool: ...

    async def execute(
        self,
        source: str,
        function_name: str,
        arguments: dict[str, Any],
        environment: dict[str, str],
    ) -> Any: ...


class DisabledToolExecutor:
    enabled = False

    async def execute(
        self,
        source: str,
        function_name: str,
        arguments: dict[str, Any],
        environment: dict[str, str],
    ) -> Any:
        raise ToolExecutionError("Tool execution is not configured.")


class SandboxRunnerClient:
    enabled = True

    def __init__(
        self,
        base_url: str,
        token: str,
        limits: SandboxLimits,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("TOOL_RUNNER_URL must be an internal HTTP URL.")
        if len(token.encode("utf-8")) < 32:
            raise ValueError("The tool runner token must contain at least 32 bytes.")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.limits = limits

    async def execute(
        self,
        source: str,
        function_name: str,
        arguments: dict[str, Any],
        environment: dict[str, str],
    ) -> Any:
        try:
            arguments_json = json.dumps(
                arguments,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError("Tool arguments must be JSON values.") from exc
        if len(source.encode("utf-8")) > self.limits.max_source_bytes:
            raise ToolExecutionError("Tool source exceeds the configured size limit.")
        if len(arguments_json) > self.limits.max_input_bytes:
            raise ToolExecutionError("Tool arguments exceed the configured size limit.")
        try:
            environment_json = json.dumps(
                environment,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(
                "Workspace values must be JSON string mappings."
            ) from exc
        if len(environment_json) > self.limits.max_input_bytes:
            raise ToolExecutionError(
                "Workspace values exceed the configured size limit."
            )

        payload = {
            "source": source,
            "function_name": function_name,
            "arguments": arguments,
            "environment": environment,
        }
        try:
            timeout = self.limits.timeout_seconds + self.limits.queue_timeout_seconds + 8
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout),
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/execute",
                    headers={"Authorization": f"Bearer {self.token}"},
                    json=payload,
                ) as response:
                    if response.status_code == 429:
                        raise ToolExecutionError(
                            "All tool sandboxes are busy; retry the tool call."
                        )
                    if response.status_code != 200:
                        raise ToolExecutionError(
                            "The sandbox runner could not execute this tool."
                        )
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(raw) + len(chunk) > self.limits.max_output_bytes + 4096:
                            raise ToolExecutionError(
                                "Tool output exceeds the configured size limit."
                            )
                        raw.extend(chunk)
            result = json.loads(raw)
        except ToolExecutionError:
            raise
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            raise ToolExecutionError("The sandbox runner is unavailable.") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ToolExecutionError("The sandbox runner returned an invalid response.") from exc

        if not isinstance(result, dict) or set(result) != {"result"}:
            raise ToolExecutionError("The sandbox runner returned an invalid response.")
        try:
            encoded_result = json.dumps(
                result["result"],
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ToolExecutionError(
                "The sandbox runner returned an invalid result."
            ) from exc
        if len(encoded_result) > self.limits.max_output_bytes:
            raise ToolExecutionError("Tool output exceeds the configured size limit.")
        return result["result"]


def load_runner_token(path_value: str | None) -> str | None:
    if path_value is None:
        return None
    path = Path(path_value)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Could not read the configured tool runner token file.") from exc
    if len(token.encode("utf-8")) < 32:
        raise ValueError("The configured tool runner token is invalid.")
    return token


def create_tool_executor(limits: SandboxLimits) -> ToolExecutor:
    base_url = os.getenv("TOOL_RUNNER_URL", "").strip()
    if not base_url:
        return DisabledToolExecutor()
    token_file = os.getenv("TOOL_RUNNER_TOKEN_FILE", "").strip()
    if not token_file:
        raise ValueError("TOOL_RUNNER_TOKEN_FILE is required when the runner is enabled.")
    token = load_runner_token(token_file)
    if token is None:
        raise ValueError("The configured tool runner token is invalid.")
    return SandboxRunnerClient(base_url, token, limits)
