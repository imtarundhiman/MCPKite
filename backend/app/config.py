import logging
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv

logger = logging.getLogger("mcp_platform")
BACKEND_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_environment() -> None:
    load_dotenv(BACKEND_ENV_FILE, override=False)


load_environment()


@dataclass(frozen=True)
class AuthSettings:
    jwt_secret: str
    access_token_ttl_seconds: int
    session_ttl_seconds: int
    secure_cookies: bool
    cors_allowed_origins: tuple[str, ...]


@dataclass(frozen=True)
class ResourceStorageSettings:
    provider: Literal["s3", "azure_blob"]
    s3_bucket: str
    s3_region: str
    s3_endpoint_url: str | None
    s3_access_key_id: str | None
    s3_secret_access_key: str | None
    azure_connection_string: str | None
    azure_container: str


def _positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return parsed


def load_resource_storage_settings() -> ResourceStorageSettings:
    provider = os.getenv("RESOURCE_STORAGE_PROVIDER", "s3").strip().lower()
    if provider not in {"s3", "azure_blob"}:
        raise ValueError("RESOURCE_STORAGE_PROVIDER must be 's3' or 'azure_blob'.")

    s3_bucket = os.getenv("RESOURCE_S3_BUCKET", "webmcp-resources").strip()
    s3_region = os.getenv("RESOURCE_S3_REGION", "us-east-1").strip()
    azure_container = os.getenv(
        "RESOURCE_AZURE_CONTAINER", "webmcp-resources"
    ).strip()
    if not s3_bucket:
        raise ValueError("RESOURCE_S3_BUCKET must not be blank.")
    if not s3_region:
        raise ValueError("RESOURCE_S3_REGION must not be blank.")
    access_key_id = os.getenv("AWS_ACCESS_KEY_ID", "").strip() or None
    secret_access_key = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip() or None
    if (access_key_id is None) != (secret_access_key is None):
        raise ValueError(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be configured together."
        )
    if not azure_container:
        raise ValueError("RESOURCE_AZURE_CONTAINER must not be blank.")

    azure_connection_string = (
        os.getenv("RESOURCE_AZURE_CONNECTION_STRING", "").strip() or None
    )
    if provider == "azure_blob" and azure_connection_string is None:
        raise ValueError(
            "RESOURCE_AZURE_CONNECTION_STRING is required when "
            "RESOURCE_STORAGE_PROVIDER is 'azure_blob'."
        )

    return ResourceStorageSettings(
        provider=provider,
        s3_bucket=s3_bucket,
        s3_region=s3_region,
        s3_endpoint_url=os.getenv("RESOURCE_S3_ENDPOINT_URL", "").strip() or None,
        s3_access_key_id=access_key_id,
        s3_secret_access_key=secret_access_key,
        azure_connection_string=azure_connection_string,
        azure_container=azure_container,
    )


def load_auth_settings(jwt_secret: str | None = None) -> AuthSettings:
    resolved_secret = jwt_secret or os.getenv("AUTH_JWT_SECRET") or None
    if resolved_secret is None:
        resolved_secret = secrets.token_urlsafe(48)
        logger.warning(
            "AUTH_JWT_SECRET is unset; using an ephemeral key. "
            "Configure a persistent value for production deployments."
        )
    if len(resolved_secret.encode("utf-8")) < 32:
        raise ValueError("AUTH_JWT_SECRET must contain at least 32 bytes.")

    secure_cookies = os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower()
    if secure_cookies not in {"true", "false"}:
        raise ValueError("AUTH_COOKIE_SECURE must be either true or false.")

    cors_allowed_origins = tuple(
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )
    for origin in cors_allowed_origins:
        parsed_origin = urlsplit(origin)
        if (
            origin == "*"
            or parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.netloc
            or parsed_origin.path
            or parsed_origin.query
            or parsed_origin.fragment
            or origin != f"{parsed_origin.scheme}://{parsed_origin.netloc}"
        ):
            raise ValueError(
                "CORS_ALLOWED_ORIGINS must contain comma-separated HTTP(S) origins "
                "without paths or wildcard entries."
            )

    return AuthSettings(
        jwt_secret=resolved_secret,
        access_token_ttl_seconds=_positive_int("AUTH_ACCESS_TOKEN_TTL_SECONDS", 900),
        session_ttl_seconds=_positive_int("AUTH_SESSION_TTL_SECONDS", 14_400),
        secure_cookies=secure_cookies == "true",
        cors_allowed_origins=cors_allowed_origins,
    )
