import hmac
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthSession, User, WorkspaceMembership
from app.security import decode_access_token


@dataclass(frozen=True)
class AuthenticatedUser:
    user: User
    workspace_id: str
    role: str
    session_id: str


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session


async def require_csrf(request: Request) -> None:
    cookie_token = request.cookies.get("csrf_token", "")
    header_token = request.headers.get("x-csrf-token", "")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The CSRF token is missing or invalid.",
        )


async def get_authenticated_user(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
) -> AuthenticatedUser:
    token = request.cookies.get("studio_access")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in to continue.",
        )
    try:
        payload = decode_access_token(token, request.app.state.auth_settings.jwt_secret)
        user_id = str(payload["sub"])
        session_id = str(payload["sid"])
    except (jwt.InvalidTokenError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your sign-in has expired. Sign in again.",
        ) from exc

    auth_session = await session.get(AuthSession, session_id)
    now = datetime.now(timezone.utc)
    if (
        auth_session is None
        or auth_session.user_id != user_id
        or auth_session.revoked_at is not None
        or _as_utc(auth_session.expires_at) <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your sign-in has expired. Sign in again.",
        )

    user_and_membership = (
        await session.execute(
            select(User, WorkspaceMembership).join(
                WorkspaceMembership, WorkspaceMembership.user_id == User.id
            ).where(User.id == user_id)
        )
    ).first()
    if user_and_membership is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer part of a workspace.",
        )
    user, membership = user_and_membership
    return AuthenticatedUser(
        user=user,
        workspace_id=membership.workspace_id,
        role=membership.role,
        session_id=session_id,
    )


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def require_owner(
    current: AuthenticatedUser = Depends(get_authenticated_user),
) -> AuthenticatedUser:
    if current.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the workspace owner can perform this action.",
        )
    return current
