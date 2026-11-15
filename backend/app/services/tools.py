import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp_runtime import (
    ServerRuntime,
    register_tool_definition,
    remove_tool_definition,
)
from app.models import MCPToolDefinition, ServerDefinition
from app.sandbox_limits import SandboxLimits
from app.schemas import ToolDefinitionPage, ToolDefinitionRecord
from app.tool_contracts import ToolContract, parse_tool_source
from app.tool_executor import ToolExecutor

logger = logging.getLogger("mcp_platform")


def _record(
    definition: MCPToolDefinition,
    limits: SandboxLimits,
    execution_enabled: bool,
) -> ToolDefinitionRecord:
    contract = parse_tool_source(
        definition.source,
        max_source_bytes=limits.max_source_bytes,
        max_parameters=limits.max_parameters,
    )
    return ToolDefinitionRecord(
        id=definition.id,
        server_id=definition.server_id,
        name=contract.name,
        description=contract.description,
        source=definition.source,
        input_schema=contract.input_schema,
        execution_status="active" if execution_enabled else "disabled",
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


async def _get_server(
    session: AsyncSession,
    server_id: str,
    workspace_id: str,
) -> ServerDefinition:
    server = await session.scalar(
        select(ServerDefinition).where(
            ServerDefinition.id == server_id,
            ServerDefinition.workspace_id == workspace_id,
        )
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found in this workspace.",
        )
    return server


def _runtime(app: FastAPI, server_id: str) -> ServerRuntime:
    runtime = app.state.server_contexts.get(server_id)
    if not isinstance(runtime, ServerRuntime):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The MCP server runtime is not available. Refresh and retry.",
        )
    return runtime


def _contract(source: str, limits: SandboxLimits) -> ToolContract:
    try:
        contract = parse_tool_source(
            source,
            max_source_bytes=limits.max_source_bytes,
            max_parameters=limits.max_parameters,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if contract.name == "server_info":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The server_info tool name is reserved.",
        )
    return contract


def _publish_tool(
    runtime: ServerRuntime,
    source: str,
    contract: ToolContract,
    executor: ToolExecutor,
) -> None:
    try:
        register_tool_definition(
            runtime.server,
            source,
            contract,
            executor,
            workspace_id=runtime.workspace_id,
            workspace_value_source=runtime.workspace_value_source,
        )
    except Exception as exc:
        logger.exception("Could not publish tool %s to its MCP server", contract.name)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The tool was saved but could not be published to the MCP server.",
        ) from exc


async def list_tool_definitions(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> list[ToolDefinitionRecord]:
    await _get_server(session, server_id, workspace_id)
    definitions = (
        await session.scalars(
            select(MCPToolDefinition)
            .where(
                MCPToolDefinition.workspace_id == workspace_id,
                MCPToolDefinition.server_id == server_id,
            )
            .order_by(MCPToolDefinition.created_at, MCPToolDefinition.id)
        )
    ).all()
    limits: SandboxLimits = app.state.sandbox_limits
    executor: ToolExecutor = app.state.tool_executor
    return [
        _record(definition, limits, executor.enabled)
        for definition in definitions
    ]


async def list_tool_definition_page(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    page: int,
    page_size: int,
) -> ToolDefinitionPage:
    await _get_server(session, server_id, workspace_id)
    filters = (
        MCPToolDefinition.workspace_id == workspace_id,
        MCPToolDefinition.server_id == server_id,
    )
    total = await session.scalar(
        select(func.count()).select_from(MCPToolDefinition).where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    definitions = (
        await session.scalars(
            select(MCPToolDefinition)
            .where(*filters)
            .order_by(MCPToolDefinition.created_at, MCPToolDefinition.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    limits: SandboxLimits = app.state.sandbox_limits
    executor: ToolExecutor = app.state.tool_executor
    return ToolDefinitionPage(
        items=[
            _record(definition, limits, executor.enabled)
            for definition in definitions
        ],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_tool_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    source: str,
) -> ToolDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    limits: SandboxLimits = app.state.sandbox_limits
    executor: ToolExecutor = app.state.tool_executor
    contract = _contract(source, limits)

    async with runtime.tool_lock:
        now = datetime.now(timezone.utc)
        definition = MCPToolDefinition(
            id=str(uuid4()),
            workspace_id=workspace_id,
            server_id=server_id,
            name=contract.name,
            source=source,
            created_at=now,
            updated_at=now,
        )
        session.add(definition)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A tool with this name already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not save tool %s for server %s",
                contract.name,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the tool definition.",
            ) from exc

        if executor.enabled:
            _publish_tool(runtime, source, contract, executor)
        return _record(definition, limits, executor.enabled)


async def update_tool_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    tool_id: str,
    source: str,
) -> ToolDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    limits: SandboxLimits = app.state.sandbox_limits
    executor: ToolExecutor = app.state.tool_executor
    contract = _contract(source, limits)

    async with runtime.tool_lock:
        definition = await session.scalar(
            select(MCPToolDefinition).where(
                MCPToolDefinition.id == tool_id,
                MCPToolDefinition.server_id == server_id,
                MCPToolDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tool not found on this server.",
            )
        old_name = definition.name
        definition.name = contract.name
        definition.source = source
        definition.updated_at = datetime.now(timezone.utc)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A tool with this name already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception("Could not update tool %s on server %s", tool_id, server_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update the tool definition.",
            ) from exc

        if executor.enabled:
            try:
                remove_tool_definition(runtime.server, old_name)
                register_tool_definition(
                    runtime.server,
                    source,
                    contract,
                    executor,
                    workspace_id=runtime.workspace_id,
                    workspace_value_source=runtime.workspace_value_source,
                )
            except Exception as exc:
                logger.exception("Could not update published tool %s", tool_id)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The tool was saved but could not be published to the MCP server.",
                ) from exc
        return _record(definition, limits, executor.enabled)


async def delete_tool_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    tool_id: str,
) -> None:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    executor: ToolExecutor = app.state.tool_executor

    async with runtime.tool_lock:
        definition = await session.scalar(
            select(MCPToolDefinition).where(
                MCPToolDefinition.id == tool_id,
                MCPToolDefinition.server_id == server_id,
                MCPToolDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tool not found on this server.",
            )
        name = definition.name
        await session.delete(definition)
        try:
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception("Could not delete tool %s on server %s", tool_id, server_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not delete the tool definition.",
            ) from exc

        if executor.enabled:
            try:
                remove_tool_definition(runtime.server, name)
            except Exception as exc:
                logger.exception("Could not remove published tool %s", tool_id)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The tool was deleted but could not be removed from the MCP server.",
                ) from exc
