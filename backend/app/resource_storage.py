import logging
import json
import re
from collections.abc import Iterator, Mapping
from typing import BinaryIO, Protocol

from app.config import ResourceStorageSettings
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("mcp_platform")
MAX_RESOURCE_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_RESOURCE_UPLOAD_REQUEST_BYTES = MAX_RESOURCE_UPLOAD_BYTES + 1024 * 1024
AZURE_STORAGE_API_VERSION = "2023-11-03"
_BINARY_UPLOAD_PATH = re.compile(
    r"^/api/v1/servers/[^/]+/resources/(?:binary|[^/]+/binary)$"
)


class ResourceUploadTooLarge(Exception):
    pass


class ResourceUploadLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") not in {"POST", "PUT"}
            or _BINARY_UPLOAD_PATH.fullmatch(scope.get("path", "")) is None
        ):
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        content_length = headers.get(b"content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > MAX_RESOURCE_UPLOAD_REQUEST_BYTES:
                await self._send_too_large(send)
                return

        total_bytes = 0

        async def receive_with_limit():
            nonlocal total_bytes
            message = await receive()
            if message["type"] == "http.request":
                total_bytes += len(message.get("body", b""))
                if total_bytes > MAX_RESOURCE_UPLOAD_REQUEST_BYTES:
                    raise ResourceUploadTooLarge
            return message

        await self.app(scope, receive_with_limit, send)

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        body = json.dumps(
            {"detail": "Resource files must be 50 MiB or smaller."}
        ).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ResourceStorageError(RuntimeError):
    pass


class ResourceObjectStore(Protocol):
    def verify(self) -> None: ...

    def upload(
        self,
        object_key: str,
        content: BinaryIO,
        size_bytes: int,
        mime_type: str,
        sha256: str,
    ) -> None: ...

    def download(self, object_key: str) -> bytes: ...

    def delete(self, object_key: str) -> None: ...


class S3ResponseBody(Protocol):
    def read(self, amount: int) -> bytes: ...

    def close(self) -> None: ...


class S3Client(Protocol):
    def head_bucket(self, *, Bucket: str) -> object: ...

    def put_object(
        self,
        *,
        Bucket: str,
        Key: str,
        Body: BinaryIO,
        ContentLength: int,
        ContentType: str,
        Metadata: dict[str, str],
    ) -> object: ...

    def get_object(self, *, Bucket: str, Key: str) -> Mapping[str, S3ResponseBody]: ...

    def delete_object(self, *, Bucket: str, Key: str) -> object: ...


class BlobDownload(Protocol):
    def chunks(self) -> Iterator[bytes]: ...


class AzureContainer(Protocol):
    def exists(self) -> bool: ...

    def upload_blob(
        self,
        *,
        name: str,
        data: BinaryIO,
        length: int,
        overwrite: bool,
        content_settings: object,
        metadata: dict[str, str],
    ) -> object: ...

    def download_blob(self, blob: str, *, max_concurrency: int) -> BlobDownload: ...

    def delete_blob(self, blob: str, *, delete_snapshots: str) -> object: ...


class AzureService(Protocol):
    def get_container_client(self, container: str) -> AzureContainer: ...


class S3ResourceObjectStore:
    def __init__(self, settings: ResourceStorageSettings, client: S3Client | None = None):
        if client is None:
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                region_name=settings.s3_region,
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                config=(
                    Config(s3={"addressing_style": "path"})
                    if settings.s3_endpoint_url
                    else None
                ),
            )
        self._client = client
        self._bucket = settings.s3_bucket

    def verify(self) -> None:
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:
            logger.exception("S3 resource storage verification failed")
            raise ResourceStorageError(
                "Could not access the configured S3 resource bucket."
            ) from exc

    def upload(
        self,
        object_key: str,
        content: BinaryIO,
        size_bytes: int,
        mime_type: str,
        sha256: str,
    ) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=content,
                ContentLength=size_bytes,
                ContentType=mime_type,
                Metadata={"sha256": sha256},
            )
        except Exception as exc:
            logger.exception("S3 resource upload failed")
            raise ResourceStorageError("Could not upload the resource file.") from exc

    def download(self, object_key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
            body = response["Body"]
            try:
                content = body.read(MAX_RESOURCE_UPLOAD_BYTES + 1)
            finally:
                body.close()
        except Exception as exc:
            logger.exception("S3 resource read failed")
            raise ResourceStorageError("Could not read the resource file.") from exc
        if len(content) > MAX_RESOURCE_UPLOAD_BYTES:
            raise ResourceStorageError("Stored resource exceeds the allowed size.")
        return content

    def delete(self, object_key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except Exception as exc:
            logger.exception("S3 resource deletion failed")
            raise ResourceStorageError("Could not delete the resource file.") from exc


class AzureBlobResourceObjectStore:
    def __init__(
        self,
        settings: ResourceStorageSettings,
        service_client: AzureService | None = None,
    ):
        if service_client is None:
            from azure.storage.blob import BlobServiceClient

            if settings.azure_connection_string is None:
                raise ValueError("An Azure Blob connection string is required.")
            service_client = BlobServiceClient.from_connection_string(
                settings.azure_connection_string,
                api_version=AZURE_STORAGE_API_VERSION,
            )
        self._container = service_client.get_container_client(
            settings.azure_container
        )

    def verify(self) -> None:
        try:
            if not self._container.exists():
                raise ResourceStorageError(
                    "The configured Azure Blob container does not exist."
                )
        except ResourceStorageError:
            raise
        except Exception as exc:
            logger.exception("Azure Blob resource storage verification failed")
            raise ResourceStorageError(
                "Could not access the configured Azure Blob container."
            ) from exc

    def upload(
        self,
        object_key: str,
        content: BinaryIO,
        size_bytes: int,
        mime_type: str,
        sha256: str,
    ) -> None:
        try:
            from azure.storage.blob import ContentSettings

            self._container.upload_blob(
                name=object_key,
                data=content,
                length=size_bytes,
                overwrite=True,
                content_settings=ContentSettings(content_type=mime_type),
                metadata={"sha256": sha256},
            )
        except Exception as exc:
            logger.exception("Azure Blob resource upload failed")
            raise ResourceStorageError("Could not upload the resource file.") from exc

    def download(self, object_key: str) -> bytes:
        try:
            downloader = self._container.download_blob(
                object_key,
                max_concurrency=1,
            )
            content = bytearray()
            for chunk in downloader.chunks():
                content.extend(chunk)
                if len(content) > MAX_RESOURCE_UPLOAD_BYTES:
                    raise ResourceStorageError(
                        "Stored resource exceeds the allowed size."
                    )
        except ResourceStorageError:
            raise
        except Exception as exc:
            logger.exception("Azure Blob resource read failed")
            raise ResourceStorageError("Could not read the resource file.") from exc
        return bytes(content)

    def delete(self, object_key: str) -> None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._container.delete_blob(object_key, delete_snapshots="include")
        except ResourceNotFoundError:
            return
        except Exception as exc:
            logger.exception("Azure Blob resource deletion failed")
            raise ResourceStorageError("Could not delete the resource file.") from exc


def create_resource_object_store(
    settings: ResourceStorageSettings,
) -> ResourceObjectStore:
    if settings.provider == "s3":
        return S3ResourceObjectStore(settings)
    if settings.provider == "azure_blob":
        return AzureBlobResourceObjectStore(settings)
    raise ValueError(f"Unsupported resource storage provider: {settings.provider}")
