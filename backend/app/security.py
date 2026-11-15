import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

PASSWORD_HASHER = PasswordHash.recommended()
JWT_ISSUER = "mcpkite"
JWT_AUDIENCE = "mcpkite-api"


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return PASSWORD_HASHER.verify(password, password_hash)


def create_access_token(
    *,
    secret: str,
    user_id: str,
    session_id: str,
    expires_at: datetime,
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": user_id,
            "sid": session_id,
            "iat": now,
            "exp": expires_at,
            "iss": JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "typ": "access",
        },
        secret,
        algorithm="HS256",
    )


def decode_access_token(token: str, secret: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=JWT_AUDIENCE,
        issuer=JWT_ISSUER,
        options={"require": ["exp", "iat", "sub", "sid"]},
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("Unexpected token type.")
    return payload


def create_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_one_time_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def expires_in(seconds: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)
