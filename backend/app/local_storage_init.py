import os
import time

from app.resource_storage import AZURE_STORAGE_API_VERSION


def _initialize_azurite() -> None:
    connection_string = os.environ.get("AZURITE_INIT_CONNECTION_STRING", "").strip()
    if not connection_string:
        return

    from azure.core.exceptions import AzureError, ResourceExistsError
    from azure.storage.blob import BlobServiceClient

    service = BlobServiceClient.from_connection_string(
        connection_string,
        api_version=AZURE_STORAGE_API_VERSION,
    )
    container = service.get_container_client(os.environ["AZURITE_INIT_CONTAINER"])
    for attempt in range(60):
        try:
            container.create_container()
            return
        except ResourceExistsError:
            return
        except AzureError:
            if attempt == 59:
                raise
            time.sleep(2)


def main() -> None:
    _initialize_azurite()


if __name__ == "__main__":
    main()
