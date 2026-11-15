from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser
from app.models import (
    AuthSession,
    MCPPromptDefinition,
    MCPToolDefinition,
    ServerDefinition,
    ServerSecret,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)
from app.schemas import (
    CreatedWorkspaceInvite,
    WorkspaceInviteRecord,
    WorkspaceMemberPage,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    WorkspaceSummary,
)
from app.security import create_one_time_token, hash_token
from app.services.auth import invite_is_usable

INVITE_TTL = timedelta(days=7)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def get_workspace_record(
    session: AsyncSession,
    current: AuthenticatedUser,
) -> WorkspaceRecord:
    workspace = await session.get(Workspace, current.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found.",
        )
    return WorkspaceRecord(id=workspace.id, name=workspace.name, role=current.role)


async def get_workspace_summary(
    session: AsyncSession,
    workspace_id: str,
    execution_enabled: bool,
) -> WorkspaceSummary:
    counts = (
        await session.execute(
            select(
                select(func.count())
                .select_from(ServerDefinition)
                .where(ServerDefinition.workspace_id == workspace_id)
                .scalar_subquery()
                .label("server_count"),
                select(func.count())
                .select_from(MCPToolDefinition)
                .where(MCPToolDefinition.workspace_id == workspace_id)
                .scalar_subquery()
                .label("tool_count"),
                select(func.count())
                .select_from(MCPPromptDefinition)
                .where(MCPPromptDefinition.workspace_id == workspace_id)
                .scalar_subquery()
                .label("prompt_count"),
                select(func.count())
                .select_from(ServerSecret)
                .where(ServerSecret.workspace_id == workspace_id)
                .scalar_subquery()
                .label("secret_count"),
                select(func.count())
                .select_from(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace_id)
                .scalar_subquery()
                .label("member_count"),
            )
        )
    ).one()
    return WorkspaceSummary(
        server_count=counts.server_count,
        tool_count=counts.tool_count,
        active_tool_count=counts.tool_count if execution_enabled else 0,
        prompt_count=counts.prompt_count,
        secret_count=counts.secret_count,
        member_count=counts.member_count,
    )


async def list_workspace_members(
    session: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceMemberRecord]:
    rows = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at, User.email)
        )
    ).all()
    return [
        WorkspaceMemberRecord(
            user_id=membership.user_id,
            email=user.email,
            role=membership.role,
            joined_at=membership.created_at,
        )
        for membership, user in rows
    ]


async def list_workspace_member_page(
    session: AsyncSession,
    workspace_id: str,
    page: int,
    page_size: int,
) -> WorkspaceMemberPage:
    filters = (WorkspaceMembership.workspace_id == workspace_id,)
    total = await session.scalar(
        select(func.count())
        .select_from(WorkspaceMembership)
        .join(User, User.id == WorkspaceMembership.user_id)
        .where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    rows = (
        await session.execute(
            select(WorkspaceMembership, User)
            .join(User, User.id == WorkspaceMembership.user_id)
            .where(*filters)
            .order_by(
                WorkspaceMembership.created_at,
                User.email,
                User.id,
            )
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return WorkspaceMemberPage(
        items=[
            WorkspaceMemberRecord(
                user_id=membership.user_id,
                email=user.email,
                role=membership.role,
                joined_at=membership.created_at,
            )
            for membership, user in rows
        ],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_workspace_invite(
    session: AsyncSession,
    current: AuthenticatedUser,
) -> CreatedWorkspaceInvite:
    token = create_one_time_token()
    now = datetime.now(timezone.utc)
    invite = WorkspaceInvite(
        id=str(uuid4()),
        workspace_id=current.workspace_id,
        created_by=current.user.id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=now + INVITE_TTL,
    )
    session.add(invite)
    await session.commit()
    return CreatedWorkspaceInvite(
        id=invite.id,
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        token=token,
    )


async def list_workspace_invites(
    session: AsyncSession,
    workspace_id: str,
) -> list[WorkspaceInviteRecord]:
    rows = (
        await session.execute(
            select(WorkspaceInvite)
            .where(
                WorkspaceInvite.workspace_id == workspace_id,
                WorkspaceInvite.used_at.is_(None),
                WorkspaceInvite.revoked_at.is_(None),
            )
            .order_by(WorkspaceInvite.created_at.desc())
        )
    ).scalars().all()
    return [
        WorkspaceInviteRecord(
            id=invite.id,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
        )
        for invite in rows
        if _as_utc(invite.expires_at) > datetime.now(timezone.utc)
    ]


async def preview_invite(
    session: AsyncSession,
    token: str,
) -> tuple[Workspace, WorkspaceInvite]:
    invite = await session.scalar(
        select(WorkspaceInvite).where(WorkspaceInvite.token_hash == hash_token(token))
    )
    if not invite_is_usable(invite):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This invite is expired or has already been used.",
        )
    workspace = await session.get(Workspace, invite.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The invite workspace no longer exists.",
        )
    return workspace, invite


async def revoke_workspace_invite(
    session: AsyncSession,
    workspace_id: str,
    invite_id: str,
) -> None:
    invite = await session.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.id == invite_id,
            WorkspaceInvite.workspace_id == workspace_id,
        )
    )
    if invite is None or invite.used_at is not None or invite.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active invite not found.",
        )
    invite.revoked_at = datetime.now(timezone.utc)
    await session.commit()


async def remove_workspace_member(
    session: AsyncSession,
    workspace_id: str,
    user_id: str,
) -> None:
    membership = await session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace member not found.",
        )
    if membership.role == "owner":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The workspace owner cannot be removed.",
        )
    await session.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await session.execute(
        delete(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id)
    )
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()
