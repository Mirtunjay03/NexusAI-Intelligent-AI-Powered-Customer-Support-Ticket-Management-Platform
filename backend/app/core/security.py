from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _password_hash.verify(password, password_hash)


def create_access_token(subject: str, settings: Settings | None = None) -> str:
    config = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=config.jwt_access_token_expire_minutes),
    }
    return jwt.encode(payload, config.signing_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings | None = None) -> dict[str, Any]:
    config = settings or get_settings()
    return jwt.decode(token, config.signing_secret, algorithms=["HS256"])
