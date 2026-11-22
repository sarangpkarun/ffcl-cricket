import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.models import Match, Session, User
from app.db.session import SessionLocal, get_session
from app.realtime import channel, client

router = APIRouter()
PING_SECONDS = 25
AUTH_TIMEOUT_SECONDS = 5


async def receive_token(ws: WebSocket) -> str | None:
    """The first message must be {"type":"auth","token":...}; tokens never travel in URLs."""
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS))
        return first.get("token") if first.get("type") == "auth" else None
    except (TimeoutError, ValueError, AttributeError, WebSocketDisconnect):
        return None


@contextlib.asynccontextmanager
async def ws_db(ws: WebSocket) -> AsyncIterator[AsyncSession]:
    """A short-lived DB session; honours dependency overrides so tests use their own engine."""
    override = ws.app.dependency_overrides.get(get_session)
    if override:
        agen = override()
        db = await agen.__anext__()
        try:
            yield db
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await agen.__anext__()
    else:
        async with SessionLocal() as db:
            yield db


async def authenticate(db: AsyncSession, token: str | None) -> tuple[User, int] | None:
    """Returns (user, session id) for a valid access token on a live session."""
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except jwt.PyJWTError:
        return None
    sess = await db.get(Session, claims["sid"])
    if not sess or sess.revoked_at is not None or sess.expires_at < datetime.now(UTC):
        return None
    user = await db.get(User, int(claims["sub"]))
    return (user, sess.id) if user and user.status == "active" else None


async def session_alive(db: AsyncSession, session_id: int, user_id: int) -> User | None:
    """Re-check a long-lived socket: session still valid and user still active."""
    sess = await db.get(Session, session_id)
    if not sess or sess.revoked_at is not None or sess.expires_at < datetime.now(UTC):
        return None
    user = await db.get(User, user_id)
    if user:
        await db.refresh(user)
    return user if user and user.status == "active" else None


@router.websocket("/ws/matches/{match_id}")
async def match_socket(ws: WebSocket, match_id: int) -> None:
    await ws.accept()
    token = await receive_token(ws)
    async with ws_db(ws) as db:
        auth = await authenticate(db, token)
        match = await db.get(Match, match_id) if auth else None
        seq = match.seq if match else 0
    if not auth or not match:
        with contextlib.suppress(Exception):
            await ws.close(code=4401 if not auth else 4404)
        return

    pubsub = client().pubsub()
    tasks: list[asyncio.Task] = []
    try:
        await pubsub.subscribe(channel(match_id))
        await ws.send_text(json.dumps({"type": "hello", "seq": seq}))

        async def pump() -> None:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = msg["data"]
                    await ws.send_text(data.decode() if isinstance(data, bytes) else data)

        async def keepalive() -> None:
            while True:
                await asyncio.sleep(PING_SECONDS)
                await ws.send_text('{"type":"ping"}')

        async def drain() -> None:  # client messages are ignored; this just detects disconnects
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(f()) for f in (pump, keepalive, drain)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel(match_id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await ws.close()
