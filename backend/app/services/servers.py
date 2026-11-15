import asyncio
import logging
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp

from app.api.dependencies import AuthenticatedUser
from app.mcp_runtime import (
    BearerTokenGuard,
    ServerRuntime,
    create_fastmcp_app,
    start_fastmcp_app,
    stop_fastmcp_app,
    update_fastmcp_server_name,
)
from app.models import (
    MCPPromptDefinition,
    MCPResourceDefinition,
    MCPToolDefinition,
    ServerDefinition,
    ServerSecret,
)
from app.prompt_contracts import PromptContract, prompt_contract_from_record
from app.resource_contracts import ResourceContract, resource_contract_from_record
from app.resource_storage import ResourceObjectStore, ResourceStorageError
from app.schemas import (
    CreateServerRequest,
    ServerDeletionResult,
    ServerDeletionSummary,
    ServerRegistryPage,
    ServerRecord,
    UpdateServerRequest,
    UpdateServerSecurityRequest,
)
from app.tool_contracts import ToolContract, parse_tool_source

logger = logging.getLogger("mcp_platform")
RECENT_SERVER_LIMIT = 5


def _server_record(
    definition: ServerDefinition,
    secret: ServerSecret | None,
) -> ServerRecord:
    return ServerRecord(
        id=definition.id,
        name=definition.name,
        description=definition.description,
        created_at=definition.created_at,
        endpoint_path=definition.endpoint_path,
        auth_mode="protected" if definition.auth_required else "normal",
        secret_id=secret.id if secret is not None else None,
        secret_name=secret.name if secret is not None else None,
    )


def _publish_server(
    app: FastAPI,
    record: ServerRecord,
    mounted_app: ASGIApp,
    runtime: ServerRuntime,
) -> None:
    # Keep this block free of await points; mounted routes and runtime state
    # must become visible together on the single-worker event loop.
    app.mount(
        record.endpoint_path.rstrip("/"),
        mounted_app,
        name=f"mcp_{record.id}",
    )
    app.state.server_contexts[record.id] = runtime


async def restore_servers(app: FastAPI) -> None:
    async with app.state.session_factory() as session:
        rows = (
            await session.execute(
                select(ServerDefinition, ServerSecret)
                .outerjoin(ServerSecret, ServerSecret.server_id == ServerDefinition.id)
                .order_by(ServerDefinition.created_at)
            )
        ).all()
        tool_definitions = (
            await session.scalars(
                select(MCPToolDefinition).order_by(
                    MCPToolDefinition.created_at,
                    MCPToolDefinition.id,
                )
            )
        ).all()
        prompt_definitions = (
            await session.scalars(
                select(MCPPromptDefinition).order_by(
                    MCPPromptDefinition.created_at,
                    MCPPromptDefinition.id,
                )
            )
        ).all()
        resource_definitions = (
            await session.scalars(
                select(MCPResourceDefinition).order_by(
                    MCPResourceDefinition.created_at,
                    MCPResourceDefinition.id,
                )
            )
        ).all()

    tools_by_server: dict[str, list[tuple[str, ToolContract]]] = {}
    for definition in tool_definitions:
        contract = parse_tool_source(
            definition.source,
            max_source_bytes=app.state.sandbox_limits.max_source_bytes,
            max_parameters=app.state.sandbox_limits.max_parameters,
        )
        if contract.name == "server_info":
            raise RuntimeError("The server_info tool name is reserved.")
        tools_by_server.setdefault(definition.server_id, []).append(
            (definition.source, contract)
        )

    prompts_by_server: dict[str, list[PromptContract]] = {}
    for definition in prompt_definitions:
        prompts_by_server.setdefault(definition.server_id, []).append(
            prompt_contract_from_record(definition)
        )

    resources_by_server: dict[str, list[ResourceContract]] = {}
    for definition in resource_definitions:
        resources_by_server.setdefault(definition.server_id, []).append(
            resource_contract_from_record(definition)
        )

    for definition, secret in rows:
        if definition.auth_required and secret is None:
            raise RuntimeError(
                f"Protected MCP server {definition.id} has no assigned secret."
            )
        record = _server_record(definition, secret)
        mcp_app, bearer_guard, mounted_app, mcp_server = create_fastmcp_app(
            record,
            secret.token_hash if definition.auth_required and secret else None,
            workspace_id=definition.workspace_id or "",
            workspace_value_source=app.state.workspace_value_resolver,
            tool_definitions=tuple(tools_by_server.get(definition.id, ())),
            prompt_definitions=tuple(prompts_by_server.get(definition.id, ())),
            resource_definitions=tuple(resources_by_server.get(definition.id, ())),
            tool_executor=app.state.tool_executor,
            resource_object_store=app.state.resource_object_store,
        )
        task = await start_fastmcp_app(mcp_app)
        runtime = ServerRuntime(
            task=task,
            bearer_guard=bearer_guard,
            server=mcp_server,
            workspace_id=definition.workspace_id or "",
            workspace_value_source=app.state.workspace_value_resolver,
        )
        _publish_server(app, record, mounted_app, runtime)


async def create_server(
    app: FastAPI,
    session: AsyncSession,
    current: AuthenticatedUser,
    body: CreateServerRequest,
) -> ServerRecord:
    record = ServerRecord(
        id=str(uuid4()),
        name=body.name,
        description=body.description,
        created_at=datetime.now(timezone.utc),
        endpoint_path=f"/mcp/{uuid4()}/",
        auth_mode=body.auth_mode,
    )
    definition = ServerDefinition(
        id=record.id,
        workspace_id=current.workspace_id,
        name=record.name,
        description=record.description,
        created_at=record.created_at,
        endpoint_path=record.endpoint_path,
        auth_required=body.auth_mode == "protected",
    )

    secret: ServerSecret | None = None
    if body.secret_id is not None:
        secret = await session.scalar(
            select(ServerSecret).where(
                ServerSecret.id == body.secret_id,
                ServerSecret.workspace_id == current.workspace_id,
            ).with_for_update()
        )
        if secret is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Secret not found in this workspace.",
            )
        if secret.server_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This secret is already assigned to a server.",
            )
        secret.server_id = record.id

    record = _server_record(definition, secret)
    mcp_app, bearer_guard, mounted_app, mcp_server = create_fastmcp_app(
        record,
        secret.token_hash if body.auth_mode == "protected" and secret else None,
        workspace_id=current.workspace_id,
        workspace_value_source=app.state.workspace_value_resolver,
        tool_executor=app.state.tool_executor,
    )
    try:
        task = await start_fastmcp_app(mcp_app)
    except Exception as exc:
        logger.exception("Could not start FastMCP server %s", record.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not start the FastMCP server.",
        ) from exc

    try:
        session.add(definition)
        await session.commit()
    except IntegrityError as exc:
        await stop_fastmcp_app(task)
        await session.rollback()
        logger.exception("Could not assign secret or save server %s", record.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected secret was assigned by another request.",
        ) from exc
    except SQLAlchemyError as exc:
        await stop_fastmcp_app(task)
        await session.rollback()
        logger.exception("Could not persist FastMCP server %s", record.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the server definition.",
        ) from exc

    _publish_server(
        app,
        record,
        mounted_app,
        ServerRuntime(
            task=task,
            bearer_guard=bearer_guard,
            server=mcp_server,
            workspace_id=current.workspace_id,
            workspace_value_source=app.state.workspace_value_resolver,
        ),
    )
    return record


async def list_servers(
    session: AsyncSession,
    workspace_id: str,
) -> list[ServerRecord]:
    rows = (
        await session.execute(
            select(ServerDefinition, ServerSecret)
            .outerjoin(ServerSecret, ServerSecret.server_id == ServerDefinition.id)
            .where(ServerDefinition.workspace_id == workspace_id)
            .order_by(ServerDefinition.created_at)
        )
    ).all()
    return [_server_record(definition, secret) for definition, secret in rows]


async def list_recent_servers(
    session: AsyncSession,
    workspace_id: str,
) -> list[ServerRecord]:
    rows = (
        await session.execute(
            select(ServerDefinition, ServerSecret)
            .outerjoin(ServerSecret, ServerSecret.server_id == ServerDefinition.id)
            .where(ServerDefinition.workspace_id == workspace_id)
            .order_by(ServerDefinition.created_at.desc(), ServerDefinition.id.desc())
            .limit(RECENT_SERVER_LIMIT)
        )
    ).all()
    return [_server_record(definition, secret) for definition, secret in rows]


async def list_server_registry_page(
    session: AsyncSession,
    workspace_id: str,
    page: int,
    page_size: int,
) -> ServerRegistryPage:
    total = await session.scalar(
        select(func.count())
        .select_from(ServerDefinition)
        .where(ServerDefinition.workspace_id == workspace_id)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))

    rows = (
        await session.execute(
            select(ServerDefinition, ServerSecret)
            .outerjoin(ServerSecret, ServerSecret.server_id == ServerDefinition.id)
            .where(ServerDefinition.workspace_id == workspace_id)
            .order_by(ServerDefinition.created_at, ServerDefinition.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ServerRegistryPage(
        items=[_server_record(definition, secret) for definition, secret in rows],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def get_server_deletion_summary(
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> ServerDeletionSummary:
    server = await session.scalar(
        select(ServerDefinition.id).where(
            ServerDefinition.id == server_id,
            ServerDefinition.workspace_id == workspace_id,
        )
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found in this workspace.",
        )

    tool_count = await session.scalar(
        select(func.count())
        .select_from(MCPToolDefinition)
        .where(
            MCPToolDefinition.server_id == server_id,
            MCPToolDefinition.workspace_id == workspace_id,
        )
    )
    prompt_count = await session.scalar(
        select(func.count())
        .select_from(MCPPromptDefinition)
        .where(
            MCPPromptDefinition.server_id == server_id,
            MCPPromptDefinition.workspace_id == workspace_id,
        )
    )
    resource_count = await session.scalar(
        select(func.count())
        .select_from(MCPResourceDefinition)
        .where(
            MCPResourceDefinition.server_id == server_id,
            MCPResourceDefinition.workspace_id == workspace_id,
        )
    )
    file_resource_count = await session.scalar(
        select(func.count())
        .select_from(MCPResourceDefinition)
        .where(
            MCPResourceDefinition.server_id == server_id,
            MCPResourceDefinition.workspace_id == workspace_id,
            MCPResourceDefinition.content_kind == "binary",
        )
    )
    return ServerDeletionSummary(
        tool_count=tool_count or 0,
        prompt_count=prompt_count or 0,
        resource_count=resource_count or 0,
        file_resource_count=file_resource_count or 0,
    )


async def delete_server(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> ServerDeletionResult:
    runtime = app.state.server_contexts.get(server_id)
    if not isinstance(runtime, ServerRuntime):
        runtime = None

    object_keys: list[str] = []
    runtime_shutdown_failed = False
    async with AsyncExitStack() as lock_stack:
        if runtime is not None:
            for lock in (
                runtime.tool_lock,
                runtime.prompt_lock,
                runtime.resource_lock,
            ):
                await lock_stack.enter_async_context(lock)

        definition = await session.scalar(
            select(ServerDefinition)
            .where(
                ServerDefinition.id == server_id,
                ServerDefinition.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Server not found in this workspace.",
            )

        stored_object_keys = await session.scalars(
            select(MCPResourceDefinition.object_key).where(
                MCPResourceDefinition.server_id == server_id,
                MCPResourceDefinition.workspace_id == workspace_id,
                MCPResourceDefinition.object_key.is_not(None),
            )
        )
        object_keys = [
            object_key for object_key in stored_object_keys if object_key is not None
        ]
        assigned_token = await session.scalar(
            select(ServerSecret)
            .where(
                ServerSecret.server_id == server_id,
                ServerSecret.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if assigned_token is not None:
            assigned_token.server_id = None

        try:
            await session.flush()
            await session.delete(definition)
            if runtime is not None:
                async with runtime.bearer_guard.lock:
                    await session.commit()
            else:
                await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception("Could not delete server %s", server_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not delete the server and its definitions.",
            ) from exc

        app.router.routes = [
            route
            for route in app.router.routes
            if getattr(route, "name", None) != f"mcp_{server_id}"
        ]
        app.state.server_contexts.pop(server_id, None)
        if runtime is not None:
            try:
                await stop_fastmcp_app(runtime.task)
            except Exception:
                logger.exception("Could not stop FastMCP runtime for server %s", server_id)
                runtime_shutdown_failed = True

    file_cleanup_failures = 0
    storage: ResourceObjectStore | None = app.state.resource_object_store
    for object_key in object_keys:
        if storage is None:
            logger.error(
                "No object storage provider is available to delete a resource file "
                "for server %s",
                server_id,
            )
            file_cleanup_failures += 1
            continue
        try:
            await run_in_threadpool(storage.delete, object_key)
        except ResourceStorageError:
            logger.exception(
                "Could not delete a stored resource file for server %s",
                server_id,
            )
            file_cleanup_failures += 1

    return ServerDeletionResult(
        file_cleanup_failures=file_cleanup_failures,
        runtime_shutdown_failed=runtime_shutdown_failed,
    )


async def _update_server_configuration(
    app: FastAPI,
    session: AsyncSession,
    current: AuthenticatedUser,
    server_id: str,
    body: UpdateServerSecurityRequest,
    *,
    name: str | None = None,
    description: str | None = None,
) -> ServerRecord:
    definition = await session.scalar(
        select(ServerDefinition).where(
            ServerDefinition.id == server_id,
            ServerDefinition.workspace_id == current.workspace_id,
        ).with_for_update()
    )
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found in this workspace.",
        )
    runtime: ServerRuntime | None = app.state.server_contexts.get(server_id)
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The MCP server runtime is not available. Refresh and retry.",
        )

    existing_secret = await session.scalar(
        select(ServerSecret)
        .where(ServerSecret.server_id == server_id)
        .with_for_update()
    )
    chosen_secret: ServerSecret | None = None
    if body.auth_mode == "protected":
        if body.secret_id is not None:
            chosen_secret = await session.scalar(
                select(ServerSecret).where(
                    ServerSecret.id == body.secret_id,
                    ServerSecret.workspace_id == current.workspace_id,
                ).with_for_update()
            )
            if chosen_secret is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Secret not found in this workspace.",
                )
            if chosen_secret.server_id not in {None, server_id}:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This secret is already assigned to another server.",
                )
        else:
            chosen_secret = existing_secret
        if chosen_secret is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Choose a secret before protecting this server.",
            )
        if existing_secret is not None and existing_secret.id != chosen_secret.id:
            existing_secret.server_id = None
            await session.flush()
        chosen_secret.server_id = server_id
        definition.auth_required = True
    else:
        if body.secret_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Normal servers cannot be assigned a secret.",
            )
        if existing_secret is not None:
            existing_secret.server_id = None
        definition.auth_required = False

    if name is not None:
        definition.name = name
    if description is not None:
        definition.description = description

    async with runtime.bearer_guard.lock:
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The selected secret was assigned by another request.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception("Could not update security settings for server %s", server_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update server security settings.",
            ) from exc

        runtime.bearer_guard.token_hash = (
            chosen_secret.token_hash
            if body.auth_mode == "protected" and chosen_secret
            else None
        )
        if name is not None:
            update_fastmcp_server_name(runtime.server, name)
    return _server_record(definition, chosen_secret if body.auth_mode == "protected" else None)


async def update_server_security(
    app: FastAPI,
    session: AsyncSession,
    current: AuthenticatedUser,
    server_id: str,
    body: UpdateServerSecurityRequest,
) -> ServerRecord:
    return await _update_server_configuration(app, session, current, server_id, body)


async def update_server(
    app: FastAPI,
    session: AsyncSession,
    current: AuthenticatedUser,
    server_id: str,
    body: UpdateServerRequest,
) -> ServerRecord:
    return await _update_server_configuration(
        app,
        session,
        current,
        server_id,
        body,
        name=body.name,
        description=body.description,
    )


async def stop_server_apps(app: FastAPI) -> None:
    tasks = [
        runtime.task
        for runtime in app.state.server_contexts.values()
        if isinstance(runtime, ServerRuntime)
    ]
    for task in reversed(tasks):
        await stop_fastmcp_app(task)
