import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthenticatedUser,
    get_authenticated_user,
    get_db_session,
    require_csrf,
)
from app.models import Workspace
from app.schemas import (
    AuthStatus,
    AuthUser,
    InvitePreview,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
)
from app.services.auth import (
    AuthGrant,
    login_user,
    refresh_user_session,
    register_user,
    revoke_refresh_session,
    workspace_initialized,
)
from app.services.workspaces import preview_invite

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


def _auth_user(
    *,
    user_id: str,
    email: str,
    display_name: str,
    workspace_id: str,
    workspace_name: str,
    role: str,
) -> AuthUser:
    return AuthUser(
        id=user_id,
        email=email,
        display_name=display_name,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        role=role,
    )


def _grant_user(grant: AuthGrant) -> AuthUser:
    return _auth_user(
        user_id=grant.user.id,
        email=grant.user.email,
        display_name=grant.user.display_name,
        workspace_id=grant.workspace.id,
        workspace_name=grant.workspace.name,
        role=grant.role,
    )


def _set_auth_cookies(response: Response, request: Request, grant: AuthGrant) -> None:
    settings = request.app.state.auth_settings
    seconds_remaining = max(
        0,
        int((grant.session_expires_at - datetime.now(timezone.utc)).total_seconds()),
    )
    cookie_options = {
        "secure": settings.secure_cookies,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(
        "studio_access",
        grant.access_token,
        max_age=min(settings.access_token_ttl_seconds, seconds_remaining),
        httponly=True,
        **cookie_options,
    )
    response.set_cookie(
        "studio_refresh",
        grant.refresh_token,
        max_age=seconds_remaining,
        httponly=True,
        **cookie_options,
    )


def _clear_auth_cookies(response: Response, request: Request) -> None:
    settings = request.app.state.auth_settings
    for name in ("studio_access", "studio_refresh", "csrf_token"):
        response.delete_cookie(
            name,
            path="/",
            secure=settings.secure_cookies,
            httponly=name != "csrf_token",
            samesite="lax",
        )


@router.get("/csrf")
async def get_csrf_token(request: Request, response: Response) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        "csrf_token",
        token,
        max_age=request.app.state.auth_settings.session_ttl_seconds,
        httponly=False,
        secure=request.app.state.auth_settings.secure_cookies,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token}


@router.get("/status", response_model=AuthStatus)
async def get_auth_status(
    session: AsyncSession = Depends(get_db_session),
) -> AuthStatus:
    return AuthStatus(workspace_initialized=await workspace_initialized(session))


@router.post(
    "/register",
    response_model=AuthUser,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def register(
    body: RegisterRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    grant = await register_user(request.app, session, body)
    _set_auth_cookies(response, request, grant)
    return _grant_user(grant)


@router.post("/login", response_model=AuthUser, dependencies=[Depends(require_csrf)])
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    grant = await login_user(request.app, session, body)
    _set_auth_cookies(response, request, grant)
    return _grant_user(grant)


@router.post("/refresh", response_model=AuthUser, dependencies=[Depends(require_csrf)])
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    grant = await refresh_user_session(
        request.app,
        session,
        request.cookies.get("studio_refresh"),
    )
    _set_auth_cookies(response, request, grant)
    return _grant_user(grant)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)])
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await revoke_refresh_session(
        session,
        request.cookies.get("studio_refresh"),
    )
    _clear_auth_cookies(response, request)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthUser)
async def get_me(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    workspace = await session.get(Workspace, current.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer part of a workspace.",
        )
    return _auth_user(
        user_id=current.user.id,
        email=current.user.email,
        display_name=current.user.display_name,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        role=current.role,
    )


@router.patch(
    "/me",
    response_model=AuthUser,
    dependencies=[Depends(require_csrf)],
)
async def update_me(
    body: UpdateProfileRequest,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> AuthUser:
    workspace = await session.get(Workspace, current.workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account is no longer part of a workspace.",
        )

    current.user.display_name = body.display_name
    await session.commit()
    return _auth_user(
        user_id=current.user.id,
        email=current.user.email,
        display_name=current.user.display_name,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        role=current.role,
    )


@router.get("/invites/{token}", response_model=InvitePreview)
async def get_invite_preview(
    token: str,
    session: AsyncSession = Depends(get_db_session),
) -> InvitePreview:
    workspace, invite = await preview_invite(session, token)
    return InvitePreview(
        workspace_name=workspace.name,
        expires_at=invite.expires_at,
    )
