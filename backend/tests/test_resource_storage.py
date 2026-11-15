import io

import pytest
from azure.core.exceptions import ResourceNotFoundError

from app.config import ResourceStorageSettings, load_resource_storage_settings
from app.resource_storage import (
    AzureBlobResourceObjectStore,
    ResourceStorageError,
    S3ResourceObjectStore,
)


def _settings(provider="s3"):
    return ResourceStorageSettings(
        provider=provider,
        s3_bucket="test-resources",
        s3_region="us-east-1",
        s3_endpoint_url=None,
        s3_access_key_id=None,
        s3_secret_access_key=None,
        azure_connection_string="test-connection-string",
        azure_container="test-resources",
    )


class FakeS3Body(io.BytesIO):
    pass


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.metadata = {}

    def head_bucket(self, *, Bucket):
        assert Bucket == "test-resources"

    def put_object(
        self,
        *,
        Bucket,
        Key,
        Body,
        ContentLength,
        ContentType,
        Metadata,
    ):
        value = Body.read()
        assert len(value) == ContentLength
        self.objects[Key] = value
        self.metadata[Key] = (ContentType, Metadata)

    def get_object(self, *, Bucket, Key):
        return {"Body": FakeS3Body(self.objects[Key])}

    def delete_object(self, *, Bucket, Key):
        self.objects.pop(Key, None)


class FakeBlobDownload:
    def __init__(self, value):
        self.value = value

    def chunks(self):
        yield self.value


class FakeAzureContainer:
    def __init__(self):
        self.objects = {}
        self.content_types = {}
        self.metadata = {}

    def exists(self):
        return True

    def upload_blob(
        self,
        *,
        name,
        data,
        length,
        overwrite,
        content_settings,
        metadata,
    ):
        value = data.read()
        assert len(value) == length
        assert overwrite
        self.objects[name] = value
        self.content_types[name] = content_settings.content_type
        self.metadata[name] = metadata

    def download_blob(self, blob, *, max_concurrency):
        assert max_concurrency == 1
        return FakeBlobDownload(self.objects[blob])

    def delete_blob(self, blob, *, delete_snapshots):
        if blob not in self.objects:
            raise ResourceNotFoundError(message="Blob not found.")
        assert delete_snapshots == "include"
        del self.objects[blob]


class FakeAzureService:
    def __init__(self):
        self.container = FakeAzureContainer()

    def get_container_client(self, container):
        assert container == "test-resources"
        return self.container


def test_s3_resource_store_upload_read_and_delete():
    client = FakeS3Client()
    store = S3ResourceObjectStore(_settings(), client)
    content = b"\x00binary-content"

    store.verify()
    store.upload("resources/key", io.BytesIO(content), len(content), "image/png", "abc")

    assert store.download("resources/key") == content
    assert client.metadata["resources/key"] == (
        "image/png",
        {"sha256": "abc"},
    )
    store.delete("resources/key")
    assert client.objects == {}


def test_azure_resource_store_upload_read_and_idempotent_delete():
    service = FakeAzureService()
    store = AzureBlobResourceObjectStore(_settings("azure_blob"), service)
    content = b"\x00binary-content"

    store.verify()
    store.upload("resources/key", io.BytesIO(content), len(content), "image/png", "abc")

    assert store.download("resources/key") == content
    assert service.container.content_types["resources/key"] == "image/png"
    assert service.container.metadata["resources/key"] == {"sha256": "abc"}
    store.delete("resources/key")
    store.delete("resources/key")
    assert service.container.objects == {}


def test_resource_storage_rejects_partial_s3_credentials(monkeypatch):
    monkeypatch.setenv("RESOURCE_STORAGE_PROVIDER", "s3")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "access")
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(ValueError, match="must be configured together"):
        load_resource_storage_settings()


def test_azure_storage_requires_connection_string(monkeypatch):
    monkeypatch.setenv("RESOURCE_STORAGE_PROVIDER", "azure_blob")
    monkeypatch.delenv("RESOURCE_AZURE_CONNECTION_STRING", raising=False)

    with pytest.raises(ValueError, match="is required"):
        load_resource_storage_settings()


def test_object_store_rejects_oversized_downloads(monkeypatch):
    import app.resource_storage as resource_storage

    monkeypatch.setattr(resource_storage, "MAX_RESOURCE_UPLOAD_BYTES", 4)
    s3 = FakeS3Client()
    s3.objects["resources/large"] = b"12345"

    with pytest.raises(ResourceStorageError, match="exceeds the allowed size"):
        S3ResourceObjectStore(_settings(), s3).download("resources/large")

    azure_service = FakeAzureService()
    azure_service.container.objects["resources/large"] = b"12345"
    with pytest.raises(ResourceStorageError, match="exceeds the allowed size"):
        AzureBlobResourceObjectStore(
            _settings("azure_blob"),
            azure_service,
        ).download("resources/large")
