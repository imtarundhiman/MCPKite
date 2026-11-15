import pytest
from azure.storage.blob import BlobServiceClient

from app.local_storage_init import _initialize_azurite


@pytest.mark.parametrize("connection_string", [None, "", "   "])
def test_initialize_azurite_skips_without_connection_string(
    monkeypatch, connection_string
):
    if connection_string is None:
        monkeypatch.delenv("AZURITE_INIT_CONNECTION_STRING", raising=False)
    else:
        monkeypatch.setenv("AZURITE_INIT_CONNECTION_STRING", connection_string)

    _initialize_azurite()


def test_initialize_azurite_creates_container(monkeypatch):
    container = FakeContainer()
    service = FakeBlobService(container)
    calls = {}

    def fake_from_connection_string(cls, connection_string, *, api_version):
        calls["connection_string"] = connection_string
        calls["api_version"] = api_version
        return service

    monkeypatch.setenv("AZURITE_INIT_CONNECTION_STRING", "local-azurite")
    monkeypatch.setenv("AZURITE_INIT_CONTAINER", "resources")
    monkeypatch.setattr(
        BlobServiceClient,
        "from_connection_string",
        classmethod(fake_from_connection_string),
    )

    _initialize_azurite()

    assert calls["connection_string"] == "local-azurite"
    assert container.created
    assert service.container_name == "resources"


class FakeContainer:
    def __init__(self):
        self.created = False

    def create_container(self):
        self.created = True


class FakeBlobService:
    def __init__(self, container):
        self.container = container
        self.container_name = None

    def get_container_client(self, container_name):
        self.container_name = container_name
        return self.container
