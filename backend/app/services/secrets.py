import logging
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser
from app.models import ServerDefinition, ServerSecret
from app.schemas import (
    CreateSecretRequest,
    CreatedSecret,
    SecretRecord,
    SecretRegistryPage,
)
from app.security import create_one_time_token, hash_token

logger = logging.getLogger("mcp_platform")


async def list_secrets(
    session: AsyncSession,
    current: AuthenticatedUser,
) -> list[SecretRecord]:
    rows = (
        await session.execute(
            select(ServerSecret, ServerDefinition.name)
            .outerjoin(ServerDefinition, ServerDefinition.id == ServerSecret.server_id)
            .where(ServerSecret.workspace_id == current.workspace_id)
            .order_by(ServerSecret.created_at.desc())
        )
    ).all()
    return [
        SecretRecord(
            id=secret.id,
            name=secret.name,
            server_id=secret.server_id,
            server_name=server_name,
            created_at=secret.created_at,
        )
        for secret, server_name in rows
    ]


async def list_secret_page(
    session: AsyncSession,
    current: AuthenticatedUser,
    page: int,
    page_size: int,
) -> SecretRegistryPage:
    filters = (ServerSecret.workspace_id == current.workspace_id,)
    total = await session.scalar(
        select(func.count()).select_from(ServerSecret).where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    rows = (
        await session.execute(
            select(ServerSecret, ServerDefinition.name)
            .outerjoin(ServerDefinition, ServerDefinition.id == ServerSecret.server_id)
            .where(*filters)
            .order_by(ServerSecret.created_at.desc(), ServerSecret.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return SecretRegistryPage(
        items=[
            SecretRecord(
                id=secret.id,
                name=secret.name,
                server_id=secret.server_id,
                server_name=server_name,
                created_at=secret.created_at,
            )
            for secret, server_name in rows
        ],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_secret(
    session: AsyncSession,
    current: AuthenticatedUser,
    body: CreateSecretRequest,
) -> CreatedSecret:
    value = create_one_time_token()
    secret = ServerSecret(
        id=str(uuid4()),
        workspace_id=current.workspace_id,
        server_id=None,
        name=body.name,
        token_hash=hash_token(value),
        created_at=datetime.now(timezone.utc),
    )
    session.add(secret)
    try:
        await session.commit()
    except SQLAlchemyError as exc:
        await session.rollback()
        logger.exception("Could not save server secret")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not save the secret.",
        ) from exc
    return CreatedSecret(
        id=secret.id,
        name=secret.name,
        server_id=None,
        server_name=None,
        created_at=secret.created_at,
        value=value,
    )


async def delete_secret(
    session: AsyncSession,
    current: AuthenticatedUser,
    secret_id: str,
) -> None:
    secret = await session.scalar(
        select(ServerSecret).where(
            ServerSecret.id == secret_id,
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
            detail="Detach this secret from its server before deleting it.",
        )
    await session.delete(secret)
    await session.commit()
