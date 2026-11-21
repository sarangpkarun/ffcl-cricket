import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import settings

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, pw)
    except VerifyMismatchError:
        return False


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def create_access_token(user_id: int, session_id: int) -> str:
    exp = datetime.now(UTC) + timedelta(minutes=settings.access_ttl_minutes)
    return jwt.encode(
        {"sub": str(user_id), "sid": session_id, "exp": exp}, settings.jwt_secret, algorithm="HS256"
    )


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
