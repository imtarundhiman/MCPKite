import logging
import hashlib
import re
from dataclasses import replace
from datetime import datetime, timezone
from http import HTTPStatus
from uuid import uuid4

from fastapi import FastAPI, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.mcp_runtime import (
    ServerRuntime,
    register_resource_definition,
    remove_resource_definition,
)
from app.models import MCPResourceDefinition, ServerDefinition
from app.resource_mime_types import resolve_binary_resource_mime_type
from app.resource_contracts import (
    ResourceContract,
    resource_contract_from_record,
    resource_contract_from_request,
)
from app.resource_storage import (
    MAX_RESOURCE_UPLOAD_BYTES,
    ResourceObjectStore,
    ResourceStorageError,
)
from app.schemas import (
    ResourceDefinitionPage,
    ResourceDefinitionRecord,
    SaveBinaryResourceMetadataRequest,
    SaveResourceDefinitionRequest,
)

logger = logging.getLogger("mcp_platform")
UPLOAD_CHUNK_BYTES = 1024 * 1024
_CONTROL_CHARACTER = re.compile(r"[\x00-\x1f\x7f]")


async def _get_server(
    session: AsyncSession,
    server_id: str,
    workspace_id: str,
) -> ServerDefinition:
    server = await session.scalar(
        select(ServerDefinition).where(
            ServerDefinition.id == server_id,
            ServerDefinition.workspace_id == workspace_id,
        )
    )
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Server not found in this workspace.",
        )
    return server


def _runtime(app: FastAPI, server_id: str) -> ServerRuntime:
    runtime = app.state.server_contexts.get(server_id)
    if not isinstance(runtime, ServerRuntime):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The MCP server runtime is not available. Refresh and retry.",
        )
    return runtime


def _record(definition: MCPResourceDefinition) -> ResourceDefinitionRecord:
    return ResourceDefinitionRecord(
        id=definition.id,
        server_id=definition.server_id,
        uri=definition.uri,
        name=definition.name,
        description=definition.description,
        mime_type=definition.mime_type,
        content_kind=definition.content_kind,
        content=definition.content,
        file_name=definition.file_name,
        size_bytes=definition.size_bytes,
        sha256=definition.sha256,
        audience=definition.audience,
        priority=definition.priority,
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


def _contract(body: SaveResourceDefinitionRequest) -> ResourceContract:
    try:
        return resource_contract_from_request(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _contract_from_definition(
    definition: MCPResourceDefinition,
) -> ResourceContract:
    try:
        return resource_contract_from_record(definition)
    except ValueError as exc:
        logger.exception("Persisted resource %s has an invalid contract", definition.id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="The saved resource definition is invalid.",
        ) from exc


def _storage(app: FastAPI) -> ResourceObjectStore:
    storage = getattr(app.state, "resource_object_store", None)
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Resource file storage is not configured.",
        )
    return storage


def _binary_contract(
    body: SaveBinaryResourceMetadataRequest,
    *,
    mime_type: str,
    object_key: str,
    size_bytes: int,
    checksum: str,
    updated_at: datetime,
) -> ResourceContract:
    if "{" in body.uri or "}" in body.uri:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Binary resources must use static URIs without parameters.",
        )
    try:
        contract = resource_contract_from_request(
            SaveResourceDefinitionRequest(
                uri=body.uri,
                name=body.name,
                description=body.description,
                mime_type=mime_type,
                content="",
                audience=body.audience,
                priority=body.priority,
            )
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return replace(
        contract,
        content_kind="binary",
        content=None,
        object_key=object_key,
        size_bytes=size_bytes,
        sha256=checksum,
        last_modified=updated_at.isoformat(),
    )


def _safe_file_name(upload: UploadFile) -> str:
    raw_name = upload.filename
    if raw_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Choose a file with a valid filename.",
        )
    file_name = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if (
        not file_name
        or len(file_name) > 255
        or _CONTROL_CHARACTER.search(file_name)
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The filename must be between 1 and 255 characters without control characters.",
        )
    return file_name


async def _inspect_upload(upload: UploadFile) -> tuple[int, str]:
    if upload.size is not None and upload.size > MAX_RESOURCE_UPLOAD_BYTES:
        raise HTTPException(
            status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            detail="Resource files must be 50 MiB or smaller.",
        )

    size_bytes = 0
    checksum = hashlib.sha256()
    while chunk := await upload.read(UPLOAD_CHUNK_BYTES):
        size_bytes += len(chunk)
        if size_bytes > MAX_RESOURCE_UPLOAD_BYTES:
            raise HTTPException(
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                detail="Resource files must be 50 MiB or smaller.",
            )
        checksum.update(chunk)
    await upload.seek(0)
    return size_bytes, checksum.hexdigest()


async def _upload_object(
    storage: ResourceObjectStore,
    upload: UploadFile,
    object_key: str,
    size_bytes: int,
    mime_type: str,
    checksum: str,
) -> None:
    try:
        await run_in_threadpool(
            storage.upload,
            object_key,
            upload.file,
            size_bytes,
            mime_type,
            checksum,
        )
    except ResourceStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not upload the resource file to object storage.",
        ) from exc


async def _delete_object(storage: ResourceObjectStore, object_key: str) -> None:
    try:
        await run_in_threadpool(storage.delete, object_key)
    except ResourceStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The resource record changed, but its stored file could not be cleaned up.",
        ) from exc


async def _cleanup_new_object(storage: ResourceObjectStore, object_key: str) -> None:
    try:
        await run_in_threadpool(storage.delete, object_key)
    except ResourceStorageError as exc:
        logger.exception("Could not clean up uncommitted resource object %s", object_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The resource could not be saved and its uploaded file could not be cleaned up.",
        ) from exc


def _publish_resource(
    runtime: ServerRuntime,
    contract: ResourceContract,
    storage: ResourceObjectStore,
) -> None:
    try:
        register_resource_definition(
            runtime.server,
            contract,
            storage,
            workspace_id=runtime.workspace_id,
            workspace_value_source=runtime.workspace_value_source,
        )
    except Exception as exc:
        logger.exception("Could not publish resource %s", contract.uri)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The resource was saved but could not be published to the MCP server.",
        ) from exc


async def list_resource_definitions(
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
) -> list[ResourceDefinitionRecord]:
    await _get_server(session, server_id, workspace_id)
    definitions = (
        await session.scalars(
            select(MCPResourceDefinition)
            .where(
                MCPResourceDefinition.workspace_id == workspace_id,
                MCPResourceDefinition.server_id == server_id,
            )
            .order_by(MCPResourceDefinition.created_at, MCPResourceDefinition.id)
        )
    ).all()
    return [_record(definition) for definition in definitions]


async def list_resource_definition_page(
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    page: int,
    page_size: int,
) -> ResourceDefinitionPage:
    await _get_server(session, server_id, workspace_id)
    filters = (
        MCPResourceDefinition.workspace_id == workspace_id,
        MCPResourceDefinition.server_id == server_id,
    )
    total = await session.scalar(
        select(func.count()).select_from(MCPResourceDefinition).where(*filters)
    )
    total = total or 0
    total_pages = (total + page_size - 1) // page_size
    current_page = min(page, max(total_pages, 1))
    definitions = (
        await session.scalars(
            select(MCPResourceDefinition)
            .where(*filters)
            .order_by(MCPResourceDefinition.created_at, MCPResourceDefinition.id)
            .offset((current_page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return ResourceDefinitionPage(
        items=[_record(definition) for definition in definitions],
        page=current_page,
        page_size=page_size,
        total=total,
        total_pages=total_pages,
    )


async def create_resource_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    body: SaveResourceDefinitionRequest,
) -> ResourceDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    contract = _contract(body)
    now = datetime.now(timezone.utc)

    async with runtime.resource_lock:
        definition = MCPResourceDefinition(
            id=str(uuid4()),
            workspace_id=workspace_id,
            server_id=server_id,
            uri=contract.uri,
            name=contract.name,
            description=contract.description,
            mime_type=contract.mime_type,
            content=contract.content,
            content_kind="text",
            object_key=None,
            file_name=None,
            size_bytes=None,
            sha256=None,
            audience=list(contract.audience),
            priority=contract.priority,
            created_at=now,
            updated_at=now,
        )
        session.add(definition)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A resource with this URI already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not save resource %s for server %s",
                contract.uri,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the resource definition.",
            ) from exc

        _publish_resource(
            runtime,
            _contract_from_definition(definition),
            _storage(app),
        )
        return _record(definition)


async def create_binary_resource_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    body: SaveBinaryResourceMetadataRequest,
    upload: UploadFile,
) -> ResourceDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    storage = _storage(app)
    file_name = _safe_file_name(upload)
    size_bytes, checksum = await _inspect_upload(upload)
    try:
        mime_type = resolve_binary_resource_mime_type(
            file_name,
            body.mime_type,
            upload.content_type,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    now = datetime.now(timezone.utc)
    object_key = f"resources/{uuid4().hex}"
    contract = _binary_contract(
        body,
        mime_type=mime_type,
        object_key=object_key,
        size_bytes=size_bytes,
        checksum=checksum,
        updated_at=now,
    )

    async with runtime.resource_lock:
        await _upload_object(
            storage,
            upload,
            object_key,
            size_bytes,
            mime_type,
            checksum,
        )
        definition = MCPResourceDefinition(
            id=str(uuid4()),
            workspace_id=workspace_id,
            server_id=server_id,
            uri=contract.uri,
            name=contract.name,
            description=contract.description,
            mime_type=contract.mime_type,
            content_kind="binary",
            content=None,
            object_key=object_key,
            file_name=file_name,
            size_bytes=size_bytes,
            sha256=checksum,
            audience=list(contract.audience),
            priority=contract.priority,
            created_at=now,
            updated_at=now,
        )
        session.add(definition)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            await _cleanup_new_object(storage, object_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A resource with this URI already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            await _cleanup_new_object(storage, object_key)
            logger.exception(
                "Could not save binary resource %s for server %s",
                contract.uri,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not save the resource definition.",
            ) from exc

        _publish_resource(
            runtime,
            _contract_from_definition(definition),
            _storage(app),
        )
        return _record(definition)


async def update_resource_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    resource_id: str,
    body: SaveResourceDefinitionRequest,
) -> ResourceDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    contract = _contract(body)

    async with runtime.resource_lock:
        definition = await session.scalar(
            select(MCPResourceDefinition).where(
                MCPResourceDefinition.id == resource_id,
                MCPResourceDefinition.server_id == server_id,
                MCPResourceDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found on this server.",
            )
        if definition.content_kind != "text":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Binary resources must be updated through the binary resource endpoint.",
            )

        old_uri = definition.uri
        definition.uri = contract.uri
        definition.name = contract.name
        definition.description = contract.description
        definition.mime_type = contract.mime_type
        definition.content = contract.content
        definition.audience = list(contract.audience)
        definition.priority = contract.priority
        definition.updated_at = datetime.now(timezone.utc)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A resource with this URI already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not update resource %s on server %s",
                resource_id,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update the resource definition.",
            ) from exc

        try:
            remove_resource_definition(runtime.server, old_uri)
            register_resource_definition(
                runtime.server,
                _contract_from_definition(definition),
                workspace_id=runtime.workspace_id,
                workspace_value_source=runtime.workspace_value_source,
            )
        except Exception as exc:
            logger.exception("Could not update published resource %s", resource_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The resource was saved but could not be published to the MCP server.",
            ) from exc
        return _record(definition)


async def update_binary_resource_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    resource_id: str,
    body: SaveBinaryResourceMetadataRequest,
    upload: UploadFile | None,
) -> ResourceDefinitionRecord:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)
    storage = _storage(app)

    async with runtime.resource_lock:
        definition = await session.scalar(
            select(MCPResourceDefinition).where(
                MCPResourceDefinition.id == resource_id,
                MCPResourceDefinition.server_id == server_id,
                MCPResourceDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found on this server.",
            )
        if definition.content_kind != "binary" or definition.object_key is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Text resources must be updated through the text resource endpoint.",
            )

        old_uri = definition.uri
        old_object_key = definition.object_key
        file_name = definition.file_name
        size_bytes = definition.size_bytes
        checksum = definition.sha256
        object_key = old_object_key
        uploaded_new_object = False

        if upload is not None:
            file_name = _safe_file_name(upload)
            size_bytes, checksum = await _inspect_upload(upload)
            try:
                uploaded_mime_type = resolve_binary_resource_mime_type(
                    file_name,
                    body.mime_type,
                    upload.content_type,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=str(exc),
                ) from exc
            object_key = f"resources/{uuid4().hex}"
            uploaded_new_object = True
        else:
            if (
                body.mime_type is not None
                and body.mime_type.lower() != definition.mime_type.lower()
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="The MIME type can only change when replacing the file.",
                )
            uploaded_mime_type = definition.mime_type

        now = datetime.now(timezone.utc)
        contract = _binary_contract(
            body,
            mime_type=uploaded_mime_type,
            object_key=object_key,
            size_bytes=size_bytes,
            checksum=checksum,
            updated_at=now,
        )
        if uploaded_new_object and upload is not None:
            await _upload_object(
                storage,
                upload,
                object_key,
                size_bytes,
                uploaded_mime_type,
                checksum,
            )
        definition.uri = contract.uri
        definition.name = contract.name
        definition.description = contract.description
        definition.mime_type = contract.mime_type
        definition.content = None
        definition.object_key = object_key
        definition.file_name = file_name
        definition.size_bytes = size_bytes
        definition.sha256 = checksum
        definition.audience = list(contract.audience)
        definition.priority = contract.priority
        definition.updated_at = now

        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            if uploaded_new_object:
                await _cleanup_new_object(storage, object_key)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A resource with this URI already exists on the server.",
            ) from exc
        except SQLAlchemyError as exc:
            await session.rollback()
            if uploaded_new_object:
                await _cleanup_new_object(storage, object_key)
            logger.exception(
                "Could not update binary resource %s on server %s",
                resource_id,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not update the resource definition.",
            ) from exc

        try:
            remove_resource_definition(runtime.server, old_uri)
            register_resource_definition(
                runtime.server,
                _contract_from_definition(definition),
                storage,
                workspace_id=runtime.workspace_id,
                workspace_value_source=runtime.workspace_value_source,
            )
        except Exception as exc:
            logger.exception("Could not update published binary resource %s", resource_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The resource was saved but could not be published to the MCP server.",
            ) from exc

        if uploaded_new_object and old_object_key != object_key:
            await _delete_object(storage, old_object_key)
        return _record(definition)


async def delete_resource_definition(
    app: FastAPI,
    session: AsyncSession,
    workspace_id: str,
    server_id: str,
    resource_id: str,
) -> None:
    await _get_server(session, server_id, workspace_id)
    runtime = _runtime(app, server_id)

    async with runtime.resource_lock:
        definition = await session.scalar(
            select(MCPResourceDefinition).where(
                MCPResourceDefinition.id == resource_id,
                MCPResourceDefinition.server_id == server_id,
                MCPResourceDefinition.workspace_id == workspace_id,
            )
        )
        if definition is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Resource not found on this server.",
            )
        uri = definition.uri
        object_key = definition.object_key
        await session.delete(definition)
        try:
            await session.commit()
        except SQLAlchemyError as exc:
            await session.rollback()
            logger.exception(
                "Could not delete resource %s on server %s",
                resource_id,
                server_id,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not delete the resource definition.",
            ) from exc

        try:
            remove_resource_definition(runtime.server, uri)
        except Exception as exc:
            logger.exception("Could not remove published resource %s", resource_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The resource was deleted but could not be removed from the MCP server.",
            ) from exc
        if object_key is not None:
            await _delete_object(_storage(app), object_key)
