from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    AuthenticatedUser,
    get_authenticated_user,
    get_db_session,
    require_csrf,
)
from app.schemas import (
    SaveWorkspaceConfigValueRequest,
    WorkspaceConfigValuePage,
    WorkspaceConfigValueRecord,
)
from app.services.config_values import (
    create_config_value,
    delete_config_value,
    list_config_value_page,
    list_config_values,
    update_config_value,
)

router = APIRouter(prefix="/api/v1/config-values", tags=["workspace configuration"])


@router.get("", response_model=list[WorkspaceConfigValueRecord])
async def get_config_values(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[WorkspaceConfigValueRecord]:
    return await list_config_values(session, current)


@router.get("/registry", response_model=WorkspaceConfigValuePage)
async def get_config_value_registry_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceConfigValuePage:
    if page_size not in (10, 25, 50):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page size must be 10, 25, or 50.",
        )
    return await list_config_value_page(session, current, page, page_size)


@router.post(
    "",
    response_model=WorkspaceConfigValueRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_config_value_route(
    request: Request,
    body: SaveWorkspaceConfigValueRequest,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceConfigValueRecord:
    return await create_config_value(
        session,
        current,
        body,
        request.app.state.workspace_secret_cipher,
    )


@router.put(
    "/{value_id}",
    response_model=WorkspaceConfigValueRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_config_value_route(
    request: Request,
    value_id: str,
    body: SaveWorkspaceConfigValueRequest,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> WorkspaceConfigValueRecord:
    return await update_config_value(
        session,
        current,
        value_id,
        body,
        request.app.state.workspace_secret_cipher,
    )


@router.delete(
    "/{value_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_config_value_route(
    value_id: str,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await delete_config_value(session, current, value_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
