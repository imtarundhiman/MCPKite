import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AuthSession,
    ServerDefinition,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMembership,
)
from app.schemas import LoginRequest, RegisterRequest
from app.security import (
    create_access_token,
    create_one_time_token,
    create_refresh_token,
    expires_in,
    hash_password,
    hash_token,
    verify_password,
)

logger = logging.getLogger("mcp_platform")


@dataclass(frozen=True)
class AuthGrant:
    user: User
    workspace: Workspace
    role: str
    access_token: str
    refresh_token: str
    session_expires_at: datetime


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _access_token(
    app: FastAPI,
    user_id: str,
    session_id: str,
    expires_at: datetime,
) -> str:
    settings = app.state.auth_settings
    access_expires_at = min(
        expires_at,
        expires_in(settings.access_token_ttl_seconds),
    )
    return create_access_token(
        secret=settings.jwt_secret,
        user_id=user_id,
        session_id=session_id,
        expires_at=access_expires_at,
    )


def _new_session(
    app: FastAPI,
    user: User,
    workspace: Workspace,
    role: str,
) -> tuple[AuthGrant, AuthSession]:
    settings = app.state.auth_settings
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.session_ttl_seconds)
    refresh_token = create_refresh_token()
    session_id = str(uuid4())
    auth_session = AuthSession(
        id=session_id,
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_token),
        created_at=now,
        expires_at=expires_at,
    )
    return AuthGrant(
        user=user,
        workspace=workspace,
        role=role,
        access_token=_access_token(app, user.id, session_id, expires_at),
        refresh_token=refresh_token,
        session_expires_at=expires_at,
    ), auth_session


async def workspace_initialized(session: AsyncSession) -> bool:
    return (
        await session.execute(
            select(Workspace.id).where(Workspace.bootstrap_key == "primary")
        )
    ).scalar_one_or_none() is not None


async def register_user(
    app: FastAPI,
    session: AsyncSession,
    body: RegisterRequest,
) -> AuthGrant:
    user = User(
        id=str(uuid4()),
        email=body.email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        created_at=datetime.now(timezone.utc),
    )

    try:
        async with session.begin():
            existing_user = await session.scalar(
                select(User.id).where(User.email == body.email)
            )
            if existing_user is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An account with this email already exists.",
                )
            session.add(user)

            workspace = await session.scalar(
                select(Workspace).where(Workspace.bootstrap_key == "primary")
            )
            if workspace is None:
                if body.invite_token:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This invite is no longer valid.",
                    )
                if body.workspace_name is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="A workspace name is required for the first account.",
                    )
                workspace = Workspace(
                    id=str(uuid4()),
                    name=body.workspace_name,
                    bootstrap_key="primary",
                    created_at=datetime.now(timezone.utc),
                )
                session.add(workspace)
                await session.flush()
                session.add(
                    WorkspaceMembership(
                        user_id=user.id,
                        workspace_id=workspace.id,
                        role="owner",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await session.execute(
                    update(ServerDefinition)
                    .where(ServerDefinition.workspace_id.is_(None))
                    .values(workspace_id=workspace.id)
                )
                role = "owner"
            else:
                if not body.invite_token:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="New accounts need a valid workspace invite.",
                    )
                invite = await session.scalar(
                    select(WorkspaceInvite)
                    .where(
                        WorkspaceInvite.token_hash == hash_token(body.invite_token),
                        WorkspaceInvite.workspace_id == workspace.id,
                    )
                    .with_for_update()
                )
                if not invite_is_usable(invite):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="This invite is expired or has already been used.",
                    )
                invite.used_at = datetime.now(timezone.utc)
                session.add(
                    WorkspaceMembership(
                        user_id=user.id,
                        workspace_id=workspace.id,
                        role="member",
                        created_at=datetime.now(timezone.utc),
                    )
                )
                role = "member"

            grant, auth_session = _new_session(app, user, workspace, role)
            session.add(auth_session)
            await session.flush()
    except IntegrityError as exc:
        logger.info("Registration lost a uniqueness race for %s", body.email)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account or workspace was created by another request. Try signing in.",
        ) from exc

    return grant


def invite_is_usable(invite: WorkspaceInvite | None) -> bool:
    return (
        invite is not None
        and invite.used_at is None
        and invite.revoked_at is None
        and _as_utc(invite.expires_at) > datetime.now(timezone.utc)
    )


async def login_user(
    app: FastAPI,
    session: AsyncSession,
    body: LoginRequest,
) -> AuthGrant:
    row = (
        await session.execute(
            select(User, WorkspaceMembership, Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(User.email == body.email)
        )
    ).first()
    if row is None or not verify_password(body.password, row[0].password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    user, membership, workspace = row
    grant, auth_session = _new_session(app, user, workspace, membership.role)
    session.add(auth_session)
    await session.commit()
    return grant


async def refresh_user_session(
    app: FastAPI,
    session: AsyncSession,
    refresh_token: str | None,
) -> AuthGrant:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your sign-in has expired. Sign in again.",
        )
    auth_session = await session.scalar(
        select(AuthSession)
        .where(AuthSession.refresh_token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    if (
        auth_session is None
        or auth_session.revoked_at is not None
        or _as_utc(auth_session.expires_at) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your sign-in has expired. Sign in again.",
        )

    row = (
        await session.execute(
            select(User, WorkspaceMembership, Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.user_id == User.id)
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(User.id == auth_session.user_id)
        )
    ).first()
    if row is None:
        auth_session.revoked_at = now
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer part of a workspace.",
        )

    user, membership, workspace = row
    new_refresh_token = create_refresh_token()
    auth_session.refresh_token_hash = hash_token(new_refresh_token)
    await session.commit()
    return AuthGrant(
        user=user,
        workspace=workspace,
        role=membership.role,
        access_token=_access_token(
            app, user.id, auth_session.id, _as_utc(auth_session.expires_at)
        ),
        refresh_token=new_refresh_token,
        session_expires_at=_as_utc(auth_session.expires_at),
    )


async def revoke_refresh_session(
    session: AsyncSession,
    refresh_token: str | None,
) -> None:
    if not refresh_token:
        return
    auth_session = await session.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_token(refresh_token)
        )
    )
    if auth_session is not None and auth_session.revoked_at is None:
        auth_session.revoked_at = datetime.now(timezone.utc)
        await session.commit()
