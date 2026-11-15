from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AuthenticatedUser, get_authenticated_user, get_db_session, require_csrf
from app.schemas import (
    CreateServerRequest,
    PromptDefinitionPage,
    PromptDefinitionRecord,
    ResourceDefinitionPage,
    ResourceDefinitionRecord,
    SaveBinaryResourceMetadataRequest,
    SaveResourceDefinitionRequest,
    SaveToolDefinitionRequest,
    SavePromptDefinitionRequest,
    ServerDeletionResult,
    ServerDeletionSummary,
    ServerRegistryPage,
    ServerRecord,
    ToolDefinitionPage,
    ToolDefinitionRecord,
    UpdateServerRequest,
    UpdateServerSecurityRequest,
)
from app.services.servers import (
    create_server as create_server_service,
    delete_server as delete_server_service,
    get_server_deletion_summary as get_server_deletion_summary_service,
    list_recent_servers as list_recent_servers_service,
    list_server_registry_page as list_server_registry_page_service,
    list_servers as list_servers_service,
    update_server as update_server_service,
    update_server_security as update_server_security_service,
)
from app.services.tools import (
    create_tool_definition,
    delete_tool_definition,
    list_tool_definition_page as list_tool_definition_page_service,
    list_tool_definitions,
    update_tool_definition,
)
from app.services.prompts import (
    create_prompt_definition,
    delete_prompt_definition,
    list_prompt_definition_page as list_prompt_definition_page_service,
    list_prompt_definitions,
    update_prompt_definition,
)
from app.services.resources import (
    create_binary_resource_definition,
    create_resource_definition,
    delete_resource_definition,
    list_resource_definition_page as list_resource_definition_page_service,
    list_resource_definitions,
    update_binary_resource_definition,
    update_resource_definition,
)

router = APIRouter(prefix="/api/v1/servers", tags=["servers"])


def _validate_page_size(page_size: int) -> int:
    if page_size not in (10, 12, 25, 50):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page size must be 10, 12, 25, or 50.",
        )
    return page_size


def _parse_binary_resource_metadata(payload: str) -> SaveBinaryResourceMetadataRequest:
    try:
        return SaveBinaryResourceMetadataRequest.model_validate_json(payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=exc.errors(),
        ) from exc


@router.get("", response_model=list[ServerRecord])
async def list_servers(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ServerRecord]:
    return await list_servers_service(session, current.workspace_id)


@router.get("/recent", response_model=list[ServerRecord])
async def list_recent_servers(
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ServerRecord]:
    return await list_recent_servers_service(session, current.workspace_id)


@router.get("/registry", response_model=ServerRegistryPage)
async def list_server_registry_page(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerRegistryPage:
    if page_size not in (10, 25, 50):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Page size must be 10, 25, or 50.",
        )
    return await list_server_registry_page_service(
        session,
        current.workspace_id,
        page,
        page_size,
    )


@router.post(
    "",
    response_model=ServerRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_server(
    body: CreateServerRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerRecord:
    return await create_server_service(request.app, session, current, body)


@router.patch(
    "/{server_id}",
    response_model=ServerRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_server(
    server_id: str,
    body: UpdateServerRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerRecord:
    return await update_server_service(
        request.app,
        session,
        current,
        server_id,
        body,
    )


@router.patch(
    "/{server_id}/security",
    response_model=ServerRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_server_security(
    server_id: str,
    body: UpdateServerSecurityRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerRecord:
    return await update_server_security_service(
        request.app,
        session,
        current,
        server_id,
        body,
    )


@router.get(
    "/{server_id}/deletion-summary",
    response_model=ServerDeletionSummary,
)
async def get_server_deletion_summary(
    server_id: str,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerDeletionSummary:
    return await get_server_deletion_summary_service(
        session,
        current.workspace_id,
        server_id,
    )


@router.delete(
    "/{server_id}",
    response_model=ServerDeletionResult,
    dependencies=[Depends(require_csrf)],
)
async def delete_server(
    server_id: str,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ServerDeletionResult:
    return await delete_server_service(
        request.app,
        session,
        current.workspace_id,
        server_id,
    )


@router.get("/{server_id}/tools", response_model=list[ToolDefinitionRecord])
async def list_tools(
    server_id: str,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ToolDefinitionRecord]:
    return await list_tool_definitions(
        request.app,
        session,
        current.workspace_id,
        server_id,
    )


@router.get(
    "/{server_id}/tools/page",
    response_model=ToolDefinitionPage,
)
async def list_tool_page(
    server_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ToolDefinitionPage:
    return await list_tool_definition_page_service(
        request.app,
        session,
        current.workspace_id,
        server_id,
        page,
        _validate_page_size(page_size),
    )


@router.post(
    "/{server_id}/tools",
    response_model=ToolDefinitionRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_tool(
    server_id: str,
    body: SaveToolDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ToolDefinitionRecord:
    return await create_tool_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        body.source,
    )


@router.put(
    "/{server_id}/tools/{tool_id}",
    response_model=ToolDefinitionRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_tool(
    server_id: str,
    tool_id: str,
    body: SaveToolDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ToolDefinitionRecord:
    return await update_tool_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        tool_id,
        body.source,
    )


@router.delete(
    "/{server_id}/tools/{tool_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_tool(
    server_id: str,
    tool_id: str,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_tool_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        tool_id,
    )


@router.get(
    "/{server_id}/prompts",
    response_model=list[PromptDefinitionRecord],
)
async def list_prompts(
    server_id: str,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[PromptDefinitionRecord]:
    return await list_prompt_definitions(
        session,
        current.workspace_id,
        server_id,
    )


@router.get(
    "/{server_id}/prompts/page",
    response_model=PromptDefinitionPage,
)
async def list_prompt_page(
    server_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> PromptDefinitionPage:
    return await list_prompt_definition_page_service(
        session,
        current.workspace_id,
        server_id,
        page,
        _validate_page_size(page_size),
    )


@router.post(
    "/{server_id}/prompts",
    response_model=PromptDefinitionRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_prompt(
    server_id: str,
    body: SavePromptDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> PromptDefinitionRecord:
    return await create_prompt_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        body,
    )


@router.put(
    "/{server_id}/prompts/{prompt_id}",
    response_model=PromptDefinitionRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_prompt(
    server_id: str,
    prompt_id: str,
    body: SavePromptDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> PromptDefinitionRecord:
    return await update_prompt_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        prompt_id,
        body,
    )


@router.delete(
    "/{server_id}/prompts/{prompt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_prompt(
    server_id: str,
    prompt_id: str,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_prompt_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        prompt_id,
    )


@router.get(
    "/{server_id}/resources",
    response_model=list[ResourceDefinitionRecord],
)
async def list_resources(
    server_id: str,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[ResourceDefinitionRecord]:
    return await list_resource_definitions(
        session,
        current.workspace_id,
        server_id,
    )


@router.get(
    "/{server_id}/resources/page",
    response_model=ResourceDefinitionPage,
)
async def list_resource_page(
    server_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=10, le=50),
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResourceDefinitionPage:
    return await list_resource_definition_page_service(
        session,
        current.workspace_id,
        server_id,
        page,
        _validate_page_size(page_size),
    )


@router.post(
    "/{server_id}/resources/binary",
    response_model=ResourceDefinitionRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_binary_resource(
    server_id: str,
    request: Request,
    metadata: Annotated[str, Form(max_length=8_192)],
    file: Annotated[UploadFile, File()],
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResourceDefinitionRecord:
    return await create_binary_resource_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        _parse_binary_resource_metadata(metadata),
        file,
    )


@router.put(
    "/{server_id}/resources/{resource_id}/binary",
    response_model=ResourceDefinitionRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_binary_resource(
    server_id: str,
    resource_id: str,
    request: Request,
    metadata: Annotated[str, Form(max_length=8_192)],
    file: Annotated[UploadFile | None, File()] = None,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResourceDefinitionRecord:
    return await update_binary_resource_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        resource_id,
        _parse_binary_resource_metadata(metadata),
        file,
    )


@router.post(
    "/{server_id}/resources",
    response_model=ResourceDefinitionRecord,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def create_resource(
    server_id: str,
    body: SaveResourceDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResourceDefinitionRecord:
    return await create_resource_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        body,
    )


@router.put(
    "/{server_id}/resources/{resource_id}",
    response_model=ResourceDefinitionRecord,
    dependencies=[Depends(require_csrf)],
)
async def update_resource(
    server_id: str,
    resource_id: str,
    body: SaveResourceDefinitionRequest,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> ResourceDefinitionRecord:
    return await update_resource_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        resource_id,
        body,
    )


@router.delete(
    "/{server_id}/resources/{resource_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_resource(
    server_id: str,
    resource_id: str,
    request: Request,
    current: AuthenticatedUser = Depends(get_authenticated_user),
    session: AsyncSession = Depends(get_db_session),
) -> None:
    await delete_resource_definition(
        request.app,
        session,
        current.workspace_id,
        server_id,
        resource_id,
    )
