import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from app.api.routes.auth import router as auth_router
from app.api.routes.config_values import router as config_values_router
from app.api.routes.health import router as health_router
from app.api.routes.servers import router as servers_router
from app.api.routes.secrets import router as secrets_router
from app.api.routes.workspaces import router as workspaces_router
from app.config import load_auth_settings, load_resource_storage_settings
from app.database import Base, create_database
from app.services.servers import restore_servers, stop_server_apps
from app.sandbox_limits import SandboxLimits
from app.tool_executor import create_tool_executor
from app.workspace_config import WorkspaceSecretCipher, WorkspaceValueResolver
from app.resource_storage import (
    ResourceObjectStore,
    ResourceUploadLimitMiddleware,
    ResourceUploadTooLarge,
    create_resource_object_store,
)

DEFAULT_DATABASE_URL = "******localhost:5432/mcp_platform"


def create_app(
    database_url: str | None = None,
    initialize_schema: bool = False,
    jwt_secret: str | None = None,
    resource_object_store: ResourceObjectStore | None = None,
    workspace_secret_key: str | None = None,
) -> FastAPI:
    auth_settings = load_auth_settings(jwt_secret)
    sandbox_limits = SandboxLimits.from_environment()
    tool_executor = create_tool_executor(sandbox_limits)
    resolved_resource_object_store = (
        resource_object_store
        if resource_object_store is not None
        else create_resource_object_store(load_resource_storage_settings())
    )
    resolved_database_url = database_url or os.environ.get(
        "DATABASE_URL", DEFAULT_DATABASE_URL
    )
    engine, session_factory = create_database(resolved_database_url)
    workspace_secret_cipher = WorkspaceSecretCipher(workspace_secret_key)
    workspace_value_resolver = WorkspaceValueResolver(
        session_factory,
        workspace_secret_cipher,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.server_contexts = {}
        app.state.session_factory = session_factory
        app.state.workspace_secret_cipher = workspace_secret_cipher
        app.state.workspace_value_resolver = workspace_value_resolver
        app.state.sandbox_limits = sandbox_limits
        app.state.tool_executor = tool_executor
        app.state.resource_object_store = resolved_resource_object_store

        try:
            app.state.auth_settings = auth_settings
            if initialize_schema:
                async with engine.begin() as connection:
                    await connection.run_sync(Base.metadata.create_all)

            await restore_servers(app)
            yield
        finally:
            await stop_server_apps(app)
            await engine.dispose()

    application = FastAPI(
        title="MCPKite",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        config_values_path = request.url.path
        if not (
            config_values_path == "/api/v1/config-values"
            or config_values_path.startswith("/api/v1/config-values/")
        ):
            return await request_validation_exception_handler(request, exc)
        redacted_errors = [
            {key: value for key, value in error.items() if key != "input"}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"detail": jsonable_encoder(redacted_errors)},
        )

    async def resource_upload_too_large_handler(
        request: Request,
        exc: ResourceUploadTooLarge,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=413,
            content={"detail": "Resource files must be 50 MiB or smaller."},
        )

    application.add_exception_handler(
        ResourceUploadTooLarge,
        resource_upload_too_large_handler,
    )
    application.add_middleware(ResourceUploadLimitMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(auth_settings.cors_allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(health_router)
    application.include_router(auth_router)
    application.include_router(workspaces_router)
    application.include_router(servers_router)
    application.include_router(secrets_router)
    application.include_router(config_values_router)
    return application


app = create_app()
