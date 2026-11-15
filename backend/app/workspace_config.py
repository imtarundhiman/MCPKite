import base64
import binascii
import os
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.models import WorkspaceConfigValue

CONFIG_SECRET_KEY_ENV = "WORKSPACE_SECRET_ENCRYPTION_KEY"
MAX_WORKSPACE_VALUES = 100
MAX_WORKSPACE_ENV_BYTES = 65_536
_NONCE_BYTES = 12


class WorkspaceConfigError(Exception):
    pass


class WorkspaceValueSource(Protocol):
    async def resolve(self, workspace_id: str) -> dict[str, str]: ...


class WorkspaceSecretCipher:
    def __init__(self, encoded_key: str | None = None) -> None:
        if encoded_key is None:
            encoded_key = os.getenv(CONFIG_SECRET_KEY_ENV, "").strip()
        else:
            encoded_key = encoded_key.strip()
        if not encoded_key:
            self._aes_gcm = None
            return
        try:
            key = base64.b64decode(encoded_key, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError(
                f"{CONFIG_SECRET_KEY_ENV} must be base64-encoded key material."
            ) from exc
        if len(key) != 32:
            raise ValueError(f"{CONFIG_SECRET_KEY_ENV} must decode to exactly 32 bytes.")
        self._aes_gcm = AESGCM(key)

    def encrypt(self, workspace_id: str, name: str, value: str) -> str:
        if self._aes_gcm is None:
            raise WorkspaceConfigError(
                f"{CONFIG_SECRET_KEY_ENV} must be configured to save secrets."
            )
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aes_gcm.encrypt(
            nonce,
            value.encode("utf-8"),
            self._associated_data(workspace_id, name),
        )
        return base64.b64encode(nonce + ciphertext).decode("ascii")

    def decrypt(self, workspace_id: str, name: str, encrypted_value: str) -> str:
        if self._aes_gcm is None:
            raise WorkspaceConfigError(
                f"{CONFIG_SECRET_KEY_ENV} must be configured to use saved secrets."
            )
        try:
            payload = base64.b64decode(encrypted_value, validate=True)
            if len(payload) <= _NONCE_BYTES:
                raise ValueError
            plaintext = self._aes_gcm.decrypt(
                payload[:_NONCE_BYTES],
                payload[_NONCE_BYTES:],
                self._associated_data(workspace_id, name),
            )
            return plaintext.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, InvalidTag, ValueError) as exc:
            raise WorkspaceConfigError(
                f"Stored secret {name!r} could not be decrypted."
            ) from exc

    @staticmethod
    def _associated_data(workspace_id: str, name: str) -> bytes:
        return f"workspace-config:{workspace_id}:{name}".encode("utf-8")


class WorkspaceValueResolver:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        cipher: WorkspaceSecretCipher,
    ) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def resolve(self, workspace_id: str) -> dict[str, str]:
        async with self._session_factory() as session:
            values = (
                await session.scalars(
                    select(WorkspaceConfigValue).where(
                        WorkspaceConfigValue.workspace_id == workspace_id
                    )
                )
            ).all()

        resolved: dict[str, str] = {}
        total_bytes = 0
        for item in values:
            if item.kind == "variable" and item.value is not None:
                value = item.value
            elif item.kind == "secret" and item.encrypted_value is not None:
                value = self._cipher.decrypt(
                    workspace_id,
                    item.name,
                    item.encrypted_value,
                )
            else:
                raise WorkspaceConfigError(
                    f"Stored workspace value {item.name!r} has invalid data."
                )
            total_bytes += len(item.name.encode("utf-8")) + len(value.encode("utf-8"))
            if total_bytes > MAX_WORKSPACE_ENV_BYTES:
                raise WorkspaceConfigError(
                    "Workspace values exceed the tool runtime size limit."
                )
            resolved[item.name] = value
        return resolved
