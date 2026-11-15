from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthenticatedUser,
    get_authenticated_user,
    get_db_session,
    require_csrf,
    require_owner,
)
from app.schemas import (
    CreatedWorkspaceInvite,
    WorkspaceInviteRecord,
    WorkspaceMemberPage,
    WorkspaceMemberRecord,
    WorkspaceRecord,
    WorkspaceSummary,
)
from app.services.workspaces import (
    create_workspace_invite,
    get_workspace_record,
    get_workspace_summary,
    list_workspace_invites,
    list_workspace_member_page,
    list_workspace_members,
    remove_workspace_member,
    revoke_workspace_invite,
)

router = APIRouter(prefix="/api/v1/workspace", tags=["workspace"])


@router.get("", response_model=WorkspaceRecord)
async def get_workspace(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceRecord:
    return await get_workspace_record(session, current)


@router.get("/summary", response_model=WorkspaceSummary)
async def get_workspace_summary_endpoint(
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceSummary:
    return await get_workspace_summary(
        session,
        current.workspace_id,
        request.app.state.tool_executor.enabled,
    )


@router.get("/members", response_model=list[WorkspaceMemberRecord])
async def get_members(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkspaceMemberRecord]:
    return await list_workspace_members(session, current.workspace_id)


@router.get("/members/registry", response_model=WorkspaceMemberPage)
async def get_workspace_member_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceMemberPage:
    if page_size not in (10, 25, 50):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page size must be 10, 25, or 50.",
        )
    return await list_workspace_member_page(
        session,
        current.workspace_id,
        page,
        page_size,
    )


@router.delete(
    "/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_member(
    user_id: str,
    current: AuthenticatedUser = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await remove_workspace_member(session, current.workspace_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/invites", response_model=list[WorkspaceInviteRecord])
async def get_invites(
    current: AuthenticatedUser = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkspaceInviteRecord]:
    return await list_workspace_invites(session, current.workspace_id)


@router.post(
    "/invites",
    response_model=CreatedWorkspaceInvite,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_invite(
    current: AuthenticatedUser = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> CreatedWorkspaceInvite:
    return await create_workspace_invite(session, current)


@router.delete(
    "/invites/{invite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_invite(
    invite_id: str,
    current: AuthenticatedUser = Depends(require_owner),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await revoke_workspace_invite(session, current.workspace_id, invite_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
