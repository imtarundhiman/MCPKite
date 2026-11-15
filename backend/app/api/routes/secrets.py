from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser, get_authenticated_user, get_db_session, require_csrf
from app.schemas import (
    CreateSecretRequest,
    CreatedSecret,
    SecretRecord,
    SecretRegistryPage,
)
from app.services.secrets import (
    create_secret as create_secret_service,
    delete_secret as delete_secret_service,
    list_secret_page as list_secret_page_service,
    list_secrets as list_secrets_service,
)

router = APIRouter(prefix="/api/v1/secrets", tags=["secrets"])


@router.get("", response_model=list[SecretRecord])
async def get_secrets(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[SecretRecord]:
    return await list_secrets_service(session, current)


@router.get("/registry", response_model=SecretRegistryPage)
async def get_secret_registry_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> SecretRegistryPage:
    if page_size not in (10, 25, 50):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page size must be 10, 25, or 50.",
        )
    return await list_secret_page_service(session, current, page, page_size)


@router.post(
    "",
    response_model=CreatedSecret,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_secret(
    body: CreateSecretRequest,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> CreatedSecret:
    return await create_secret_service(session, current, body)


@router.delete(
    "/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_secret(
    secret_id: str,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> Response:
    await delete_secret_service(session, current, secret_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
