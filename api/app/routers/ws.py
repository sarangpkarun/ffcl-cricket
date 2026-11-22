import asyncio
import contextlib
import json
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


async def _authenticate(db: AsyncSession, token: str | None) -> User | None:
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
    return user if user and user.status == "active" else None


AUTH_TIMEOUT_SECONDS = 5


@router.websocket("/ws/matches/{match_id}")
async def match_socket(ws: WebSocket, match_id: int) -> None:
    """The first message must be {"type":"auth","token":<access token>}.

    The token travels in the message body, never the URL, so it can't end up in access logs.
    """
    await ws.accept()
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), AUTH_TIMEOUT_SECONDS))
        token = first.get("token") if first.get("type") == "auth" else None
    except (TimeoutError, ValueError, AttributeError, WebSocketDisconnect):
        token = None

    # Dependency overrides (tests) apply to get_session; normal runs use SessionLocal.
    override = ws.app.dependency_overrides.get(get_session)
    if override:
        agen = override()
        db = await agen.__anext__()
    else:
        agen = None
        db = SessionLocal()
    try:
        user = await _authenticate(db, token)
        match = await db.get(Match, match_id) if user else None
        seq = match.seq if match else 0
    finally:
        if agen is not None:
            with contextlib.suppress(StopAsyncIteration):
                await agen.__anext__()
        else:
            await db.close()
    if not user or not match:
        with contextlib.suppress(Exception):
            await ws.close(code=4401 if not user else 4404)
        return

    pubsub = client().pubsub()
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
    try:
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
