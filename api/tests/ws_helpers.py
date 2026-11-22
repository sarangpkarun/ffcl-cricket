import asyncio
import json

import pytest
import websockets


def token_of(actor) -> str:
    return actor.h["Authorization"].split()[1]


async def recv(ws, timeout=3):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def connect(url, token):
    """Open a socket and authenticate with the first message (tokens never go in the URL)."""
    ws = await websockets.connect(url)
    await ws.send(json.dumps({"type": "auth", "token": token}))
    return ws


async def next_change(ws, timeout=3):
    while True:
        m = await recv(ws, timeout)
        if m["type"] == "changed":
            return m


async def closed_with(url, first_message=None, token=None):
    ws = await websockets.connect(url)
    if token is not None or first_message is not None:
        await ws.send(first_message if first_message is not None else json.dumps({"type": "auth", "token": token}))
    with pytest.raises(websockets.ConnectionClosed) as e:
        await asyncio.wait_for(ws.recv(), 10)
    return e.value.rcvd.code


async def next_of(ws, kind, timeout=3):
    """Next event of a given type, skipping pings and other events."""
    while True:
        m = await recv(ws, timeout)
        if m["type"] == kind:
            return m
