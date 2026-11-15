import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp_runtime import (
    ServerRuntime,
    register_prompt_definition,
    remove_prompt_definition,
)
from app.models import MCPPromptDefinition, ServerDefinition
from app.prompt_contracts import (
    PromptContract,
    prompt_arguments_as_records,
    prompt_contract_from_request,
)
from app.schemas import (
    PromptDefinitionPage,
    PromptDefinitionRecord,
    SavePromptDefinitionRequest,
)

logger = logging.getLogger("mcp_platform")


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


def _record(definition: MCPPromptDefinition) -> PromptDefinitionRecord:
    return PromptDefinitionRecord.model_validate(definition)


def _publish_prompt(runtime: ServerRuntime, contract: PromptContract) -> None:
    try:
        register_prompt_definition(
            runtime.server,
            contract,
            workspace_id=runtime.workspace_id,
            workspace_value_source=runtime.workspace_value_source,
        )
    except Exception as exc:
        logger.exception(
            "Could not publish prompt %s to its MCP server",
            contract.name,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The prompt was saved but could not be published to the MCP server.",
        ) from exc


async def list_prompt_definitions(
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> list[PromptDefinitionRecord]:
    await _get_server(session, server_id, workspace_id)
    definitions = (
        await session.scalars(
            select(MCPPromptDefinition)
            .where(
                MCPPromptDefinition.workspace_id == workspace_id,
                MCPPromptDefinition.server_id == server_id,
            )
            .order_by(MCPPromptDefinition.created_at, MCPPromptDefinition.id)
        )
    ).all()
    return [_record(definition) for definition in definitions]


async def list_prompt_definition_page(
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    page: int,
    page_size: int,
) -> PromptDefinitionPage:
    await _get_server(session, server_id, workspace_id)
    filters = (
        MCPPromptDefinition.workspace_id == workspace_id,
        MCPPromptDefinition.server_id == server_id,
    )
    total = await session.scalar(
        select(func.count()).select_from(MCPPromptDefinition).where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    definitions = (
        await session.scalars(
            select(MCPPromptDefinition)
            .where(*filters)
            .order_by(MCPPromptDefinition.created_at, MCPPromptDefinition.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return PromptDefinitionPage(
        items=[_record(definition) for definition in definitions],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_prompt_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    body: SavePromptDefinitionRequest,
) -> PromptDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    contract = prompt_contract_from_request(body)
    now = datetime.now(timezone.utc)

    async with runtime.prompt_lock:
        definition = MCPPromptDefinition(
            id=str(uuid4()),
            workspace_id=workspace_id,
            server_id=server_id,
            name=contract.name,
            description=contract.description,
            template=contract.template,
            arguments=prompt_arguments_as_records(body.arguments),
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
                detail="A prompt with this name already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not save prompt %s for server %s",
                contract.name,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the prompt definition.",
            ) from exc

        _publish_prompt(runtime, contract)
        return _record(definition)


async def update_prompt_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    prompt_id: str,
    body: SavePromptDefinitionRequest,
) -> PromptDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    contract = prompt_contract_from_request(body)

    async with runtime.prompt_lock:
        definition = await session.scalar(
            select(MCPPromptDefinition).where(
                MCPPromptDefinition.id == prompt_id,
                MCPPromptDefinition.server_id == server_id,
                MCPPromptDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt not found on this server.",
            )

        old_name = definition.name
        definition.name = contract.name
        definition.description = contract.description
        definition.template = contract.template
        definition.arguments = prompt_arguments_as_records(body.arguments)
        definition.updated_at = datetime.now(timezone.utc)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A prompt with this name already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not update prompt %s on server %s",
                prompt_id,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update the prompt definition.",
            ) from exc

        try:
            remove_prompt_definition(runtime.server, old_name)
            register_prompt_definition(
                runtime.server,
                contract,
                workspace_id=runtime.workspace_id,
                workspace_value_source=runtime.workspace_value_source,
            )
        except Exception as exc:
            logger.exception("Could not update published prompt %s", prompt_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The prompt was saved but could not be published to the MCP server.",
            ) from exc
        return _record(definition)


async def delete_prompt_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    prompt_id: str,
) -> None:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)

    async with runtime.prompt_lock:
        definition = await session.scalar(
            select(MCPPromptDefinition).where(
                MCPPromptDefinition.id == prompt_id,
                MCPPromptDefinition.server_id == server_id,
                MCPPromptDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt not found on this server.",
            )
        name = definition.name
        await session.delete(definition)
        try:
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not delete prompt %s on server %s",
                prompt_id,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not delete the prompt definition.",
            ) from exc

        try:
            remove_prompt_definition(runtime.server, name)
        except Exception as exc:
            logger.exception("Could not remove published prompt %s", prompt_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The prompt was deleted but could not be removed from the MCP server.",
            ) from exc
