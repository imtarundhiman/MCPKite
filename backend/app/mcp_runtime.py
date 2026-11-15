import asyncio
from collections.abc import Iterable
from dataclasses import dataclass, field
import hashlib
import hashlib
import hmac
import inspect
import json
import re
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import PromptError, ResourceError, ToolError
from pydantic import Field
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from app.prompt_contracts import PromptContract
from app.resource_contracts import ResourceContract
from app.schemas import ServerRecord
from app.resource_storage import ResourceObjectStore, ResourceStorageError
from app.tool_contracts import ToolContract, signature_for_tool
from app.tool_executor import ToolExecutionError, ToolExecutor
from app.workspace_config import (
    WorkspaceConfigError,
    WorkspaceValueSource,
)

_PROMPT_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_RESOURCE_PLACEHOLDER = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")
_WORKSPACE_VALUE_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass
class BearerTokenGuard:
    token_hash: str | None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


@dataclass
class ServerRuntime:
    task: asyncio.Task[None]
    bearer_guard: BearerTokenGuard
    server: FastMCP
    workspace_id: str
    workspace_value_source: WorkspaceValueSource
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    prompt_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    resource_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BearerTokenMiddleware:
    def __init__(self, app: ASGIApp, guard: BearerTokenGuard) -> None:
        self.app = app
        self.guard = guard

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_unauthorized = False
        async with self.guard.lock:
            expected_hash = self.guard.token_hash
            if scope["type"] == "http" and expected_hash is not None:
                headers = dict(scope.get("headers", []))
                authorization = headers.get(b"authorization", b"").decode(
                    "latin-1"
                ).strip()
                scheme, separator, token = authorization.partition(" ")
                actual_hash = hash_bearer_token(token) if separator and token else ""
                is_unauthorized = (
                    scheme.lower() != "bearer"
                    or not actual_hash
                    or not hmac.compare_digest(actual_hash, expected_hash)
                )
        if is_unauthorized:
            body = json.dumps({"detail": "A valid bearer token is required."}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer realm="MCP"'),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


def hash_bearer_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_fastmcp_app(
    record: ServerRecord,
    token_hash: str | None = None,
    *,
    workspace_id: str,
    workspace_value_source: WorkspaceValueSource,
    tool_definitions: tuple[tuple[str, ToolContract], ...] = (),
    prompt_definitions: tuple[PromptContract, ...] = (),
    resource_definitions: tuple[ResourceContract, ...] = (),
    tool_executor: ToolExecutor | None = None,
    resource_object_store: ResourceObjectStore | None = None,
) -> tuple[Starlette, BearerTokenGuard, BearerTokenMiddleware, FastMCP]:
    server = FastMCP(record.name)

    def server_info() -> dict[str, str]:
        """Return basic information about this managed MCP server."""
        return {"id": record.id, "name": server.name}

    server.tool(server_info)
    if tool_executor is not None and tool_executor.enabled:
        for source, contract in tool_definitions:
            register_tool_definition(
                server,
                source,
                contract,
                tool_executor,
                workspace_id=workspace_id,
                workspace_value_source=workspace_value_source,
            )
    for contract in prompt_definitions:
        register_prompt_definition(
            server,
            contract,
            workspace_id=workspace_id,
            workspace_value_source=workspace_value_source,
        )
    for contract in resource_definitions:
        register_resource_definition(
            server,
            contract,
            resource_object_store,
            workspace_id=workspace_id,
            workspace_value_source=workspace_value_source,
        )
    mcp_app = server.http_app(path="/", stateless_http=True)
    guard = BearerTokenGuard(token_hash)
    return mcp_app, guard, BearerTokenMiddleware(mcp_app, guard), server


def update_fastmcp_server_name(server: FastMCP, name: str) -> None:
    # FastMCP exposes its name as a read-only property; update the low-level
    # name used by new initialize responses.
    server._mcp_server.name = name


def register_tool_definition(
    server: FastMCP,
    source: str,
    contract: ToolContract,
    tool_executor: ToolExecutor,
    *,
    workspace_id: str,
    workspace_value_source: WorkspaceValueSource,
) -> None:
    async def invoke_tool(**arguments: object) -> object:
        try:
            environment = await workspace_value_source.resolve(workspace_id)
            missing_values = sorted(
                set(contract.required_workspace_values) - environment.keys()
            )
            if missing_values:
                names = ", ".join(repr(name) for name in missing_values)
                if len(missing_values) == 1:
                    message = (
                        f"Workspace value {names} is not defined. "
                        "Add it under Settings > Variables & secrets."
                    )
                else:
                    message = (
                        f"Workspace values {names} are not defined. "
                        "Add them under Settings > Variables & secrets."
                    )
                raise WorkspaceConfigError(message)
            return await tool_executor.execute(
                source,
                contract.name,
                arguments,
                environment,
            )
        except WorkspaceConfigError as exc:
            raise ToolError(str(exc)) from exc
        except ToolExecutionError as exc:
            raise ToolError(str(exc)) from exc

    invoke_tool.__name__ = contract.name
    invoke_tool.__doc__ = contract.description
    invoke_tool.__signature__ = signature_for_tool(contract)
    invoke_tool.__annotations__ = {
        parameter.name: parameter.annotation
        for parameter in contract.parameters
    } | {"return": contract.return_annotation}
    server.add_tool(invoke_tool)


def remove_tool_definition(server: FastMCP, name: str) -> None:
    server._local_provider.remove_tool(name)


def register_prompt_definition(
    server: FastMCP,
    contract: PromptContract,
    *,
    workspace_id: str,
    workspace_value_source: WorkspaceValueSource,
) -> None:
    async def render_prompt(**arguments: str) -> str:
        missing_required = [
            argument.name
            for argument in contract.arguments
            if argument.required and argument.name not in arguments
        ]
        if missing_required:
            raise PromptError(
                f"Missing required prompt arguments: {', '.join(missing_required)}."
            )
        try:
            workspace_values = await workspace_value_source.resolve(workspace_id)
        except WorkspaceConfigError as exc:
            raise PromptError(str(exc)) from exc

        def substitute_workspace_value(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in workspace_values:
                raise PromptError(f"Workspace value {name!r} is not defined.")
            return workspace_values[name]

        rendered_template = _WORKSPACE_VALUE_PLACEHOLDER.sub(
            substitute_workspace_value,
            contract.template,
        )
        values = {
            argument.name: arguments.get(
                argument.name,
                argument.default_value or "",
            )
            for argument in contract.arguments
        }
        return _PROMPT_PLACEHOLDER.sub(
            lambda match: values[match.group(1)],
            rendered_template,
        )

    annotations = {
        argument.name: (
            Annotated[str, Field(description=argument.description)]
            if argument.description
            else str
        )
        for argument in contract.arguments
    }
    render_prompt.__name__ = contract.name
    render_prompt.__doc__ = contract.description
    render_prompt.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                argument.name,
                kind=inspect.Parameter.KEYWORD_ONLY,
                default=(
                    inspect.Parameter.empty
                    if argument.required
                    else argument.default_value or ""
                ),
                annotation=annotations[argument.name],
            )
            for argument in contract.arguments
        ],
        return_annotation=str,
    )
    render_prompt.__annotations__ = annotations | {"return": str}
    server.prompt(name=contract.name, description=contract.description)(
        render_prompt
    )


def remove_prompt_definition(server: FastMCP, name: str) -> None:
    server._local_provider.remove_prompt(name)


def register_resource_definition(
    server: FastMCP,
    contract: ResourceContract,
    object_store: ResourceObjectStore | None = None,
    *,
    workspace_id: str,
    workspace_value_source: WorkspaceValueSource,
) -> None:
    annotations: dict[str, object] = {}
    if contract.audience:
        annotations["audience"] = list(contract.audience)
    if contract.priority is not None:
        annotations["priority"] = contract.priority
    if contract.last_modified:
        annotations["lastModified"] = contract.last_modified

    if contract.content_kind == "binary":
        object_key = contract.object_key
        expected_size = contract.size_bytes
        expected_sha256 = contract.sha256
        if (
            object_store is None
            or object_key is None
            or expected_size is None
            or expected_sha256 is None
            or contract.uri_parameters
        ):
            raise ValueError("Binary resources require valid static storage metadata.")
        binary_store = object_store

        async def read_binary_resource() -> bytes:
            try:
                content = await run_in_threadpool(
                    binary_store.download,
                    object_key,
                )
            except ResourceStorageError as exc:
                raise ResourceError(
                    "The resource file could not be read from storage."
                ) from exc
            if (
                len(content) != expected_size
                or hashlib.sha256(content).hexdigest() != expected_sha256
            ):
                raise ResourceError("The stored resource file failed integrity validation.")
            return content

        read_binary_resource.__name__ = "read_binary_resource"
        read_binary_resource.__doc__ = contract.description
        server.resource(
            uri=contract.uri,
            name=contract.name,
            description=contract.description,
            mime_type=contract.mime_type,
            annotations=annotations,
        )(read_binary_resource)
        return

    async def read_resource(**arguments: str) -> str:
        if contract.content is None:
            raise ResourceError("The text resource content is unavailable.")

        try:
            workspace_values = await workspace_value_source.resolve(workspace_id)
        except WorkspaceConfigError as exc:
            raise ResourceError(str(exc)) from exc

        def substitute_workspace_value(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in workspace_values:
                raise ResourceError(f"Workspace value {name!r} is not defined.")
            return workspace_values[name]

        content = _WORKSPACE_VALUE_PLACEHOLDER.sub(
            substitute_workspace_value,
            contract.content,
        )

        def substitute(match: re.Match[str]) -> str:
            parameter = match.group(1)
            if parameter not in arguments:
                raise ResourceError(f"Missing resource URI parameter: {parameter}.")
            return arguments[parameter]

        return _RESOURCE_PLACEHOLDER.sub(substitute, content)

    read_resource.__name__ = "read_resource"
    read_resource.__doc__ = contract.description
    read_resource.__signature__ = inspect.Signature(
        parameters=[
            inspect.Parameter(
                parameter,
                kind=inspect.Parameter.KEYWORD_ONLY,
                annotation=str,
            )
            for parameter in contract.uri_parameters
        ],
        return_annotation=str,
    )
    read_resource.__annotations__ = {
        parameter: str for parameter in contract.uri_parameters
    } | {"return": str}
    server.resource(
        uri=contract.uri,
        name=contract.name,
        description=contract.description,
        mime_type=contract.mime_type,
        annotations=annotations,
    )(read_resource)


def remove_resource_definition(server: FastMCP, uri: str) -> None:
    try:
        server._local_provider.remove_resource(uri)
    except KeyError:
        server._local_provider.remove_template(uri)


async def _run_fastmcp_app(mcp_app: Starlette, started: asyncio.Event) -> None:
    try:
        async with mcp_app.router.lifespan_context(mcp_app):
            started.set()
            await asyncio.Event().wait()
    finally:
        started.set()


async def start_fastmcp_app(mcp_app: Starlette) -> asyncio.Task[None]:
    started = asyncio.Event()
    task = asyncio.create_task(_run_fastmcp_app(mcp_app, started))
    await started.wait()
    if task.done():
        await task
    return task


async def stop_fastmcp_app(task: asyncio.Task[None]) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def stop_fastmcp_apps(tasks: Iterable[asyncio.Task[None]]) -> None:
    for task in reversed(list(tasks)):
        await stop_fastmcp_app(task)
