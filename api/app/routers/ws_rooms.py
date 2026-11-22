import asyncio
import contextlib
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.models import ChatRoom
from app.realtime import client, publish_room, room_channel
from app.routers.ws import authenticate, receive_token, session_alive, ws_db
from app.services import chat as svc
from app.services import presence

router = APIRouter()
RECHECK_SECONDS = 25  # re-verify the session and room access this often


@router.websocket("/ws/rooms/{room_id}")
async def room_socket(ws: WebSocket, room_id: int) -> None:
    await ws.accept()
    token = await receive_token(ws)
    async with ws_db(ws) as db:
        auth = await authenticate(db, token)
        room = await db.get(ChatRoom, room_id) if auth else None
        allowed = bool(auth and room and await svc.can_read(db, room, auth[0]))
    if not auth:
        with contextlib.suppress(Exception):
            await ws.close(code=4401)
        return
    if not allowed:  # same answer for "no such room" and "not yours": ids can't be probed
        with contextlib.suppress(Exception):
            await ws.close(code=4403)
        return
    user, session_id = auth
    me = {"id": user.id, "name": user.name}

    pubsub = client().pubsub()
    tasks: list[asyncio.Task] = []
    try:
        await pubsub.subscribe(room_channel(room_id))
        if await presence.touch(room_id, user.id):
            await publish_room(room_id, {"type": "presence", "user": me, "online": True})
        await ws.send_text(json.dumps({"type": "hello", "online": await presence.online_users(room_id)}))

        async def pump() -> None:
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = msg["data"]
                    await ws.send_text(data.decode() if isinstance(data, bytes) else data)

        async def recheck() -> None:
            """Drop the socket if the session ended, the account was suspended, or access was lost."""
            while True:
                await asyncio.sleep(RECHECK_SECONDS)
                async with ws_db(ws) as db:
                    u = await session_alive(db, session_id, user.id)
                    r = await db.get(ChatRoom, room_id)
                    ok = bool(u and r and await svc.can_read(db, r, u))
                if not ok:
                    with contextlib.suppress(Exception):
                        await ws.close(code=4403)
                    return
                await ws.send_text('{"type":"ping"}')

        async def listen() -> None:
            while True:
                try:
                    data = json.loads(await ws.receive_text())
                except ValueError:
                    continue
                if isinstance(data, dict) and data.get("type") == "ping":  # keeps presence fresh
                    await presence.touch(room_id, user.id)

        tasks = [asyncio.create_task(f()) for f in (pump, recheck, listen)]
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        for t in tasks:
            t.cancel()
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(room_channel(room_id))
            await pubsub.aclose()
        with contextlib.suppress(Exception):
            await presence.leave(room_id, user.id)
            await publish_room(room_id, {"type": "presence", "user": me, "online": False})
        with contextlib.suppress(Exception):
            await ws.close()
