import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser
from app.models import WorkspaceConfigValue
from app.schemas import (
    SaveWorkspaceConfigValueRequest,
    WorkspaceConfigValuePage,
    WorkspaceConfigValueRecord,
)
from app.workspace_config import (
    MAX_WORKSPACE_VALUES,
    WorkspaceConfigError,
    WorkspaceSecretCipher,
)

logger = logging.getLogger("mcp_platform")


def _record(value: WorkspaceConfigValue) -> WorkspaceConfigValueRecord:
    return WorkspaceConfigValueRecord(
        id=value.id,
        name=value.name,
        kind=value.kind,
        value=value.value if value.kind == "variable" else None,
        created_at=value.created_at,
        updated_at=value.updated_at,
    )


def _store_value(
    value: WorkspaceConfigValue,
    workspace_id: str,
    body: SaveWorkspaceConfigValueRequest,
    cipher: WorkspaceSecretCipher,
) -> None:
    value.name = body.name
    value.kind = body.kind
    value.value = body.value if body.kind == "variable" else None
    value.encrypted_value = (
        cipher.encrypt(workspace_id, body.name, body.value)
        if body.kind == "secret"
        else None
    )
    value.updated_at = datetime.now(timezone.utc)


async def list_config_values(
    session: AsyncSession,
    current: AuthenticatedUser,
) -> list[WorkspaceConfigValueRecord]:
    values = (
        await session.scalars(
            select(WorkspaceConfigValue)
            .where(WorkspaceConfigValue.workspace_id == current.workspace_id)
            .order_by(WorkspaceConfigValue.name)
        )
    ).all()
    return [_record(value) for value in values]


async def list_config_value_page(
    session: AsyncSession,
    current: AuthenticatedUser,
    page: int,
    page_size: int,
) -> WorkspaceConfigValuePage:
    filters = (WorkspaceConfigValue.workspace_id == current.workspace_id,)
    total = await session.scalar(
        select(func.count()).select_from(WorkspaceConfigValue).where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    values = (
        await session.scalars(
            select(WorkspaceConfigValue)
            .where(*filters)
            .order_by(WorkspaceConfigValue.name, WorkspaceConfigValue.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return WorkspaceConfigValuePage(
        items=[_record(value) for value in values],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_config_value(
    session: AsyncSession,
    current: AuthenticatedUser,
    body: SaveWorkspaceConfigValueRequest,
    cipher: WorkspaceSecretCipher,
) -> WorkspaceConfigValueRecord:
    total = await session.scalar(
        select(func.count()).select_from(WorkspaceConfigValue).where(
            WorkspaceConfigValue.workspace_id == current.workspace_id
        )
    )
    if (total or 0) >= MAX_WORKSPACE_VALUES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A workspace can store at most {MAX_WORKSPACE_VALUES} values.",
        )

    now = datetime.now(timezone.utc)
    value = WorkspaceConfigValue(
        id=str(uuid4()),
        workspace_id=current.workspace_id,
        name=body.name,
        kind=body.kind,
        value=None,
        encrypted_value=None,
        created_at=now,
        updated_at=now,
    )
    try:
        _store_value(value, current.workspace_id, body, cipher)
    except WorkspaceConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    session.add(value)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workspace value with this name already exists.",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Could not save workspace configuration value (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the workspace value.",
        ) from exc
    return _record(value)


async def update_config_value(
    session: AsyncSession,
    current: AuthenticatedUser,
    value_id: str,
    body: SaveWorkspaceConfigValueRequest,
    cipher: WorkspaceSecretCipher,
) -> WorkspaceConfigValueRecord:
    value = await session.scalar(
        select(WorkspaceConfigValue).where(
            WorkspaceConfigValue.id == value_id,
            WorkspaceConfigValue.workspace_id == current.workspace_id,
        )
    )
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace value not found.",
        )
    try:
        _store_value(value, current.workspace_id, body, cipher)
    except WorkspaceConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A workspace value with this name already exists.",
        ) from exc
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Could not update workspace configuration value (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not update the workspace value.",
        ) from exc
    return _record(value)


async def delete_config_value(
    session: AsyncSession,
    current: AuthenticatedUser,
    value_id: str,
) -> None:
    value = await session.scalar(
        select(WorkspaceConfigValue).where(
            WorkspaceConfigValue.id == value_id,
            WorkspaceConfigValue.workspace_id == current.workspace_id,
        )
    )
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace value not found.",
        )
    await session.delete(value)
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.error(
            "Could not delete workspace configuration value (%s)",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not delete the workspace value.",
        ) from exc
