import asyncio
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


async def hash_password_async(pw: str) -> str:
    """argon2 is deliberately slow; run it off the event loop so live matches never stall."""
    return await asyncio.to_thread(hash_password, pw)


async def verify_password_async(pw: str, hashed: str) -> bool:
    return await asyncio.to_thread(verify_password, pw, hashed)


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
