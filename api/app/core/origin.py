"""Stop a web page on another site from opening our sockets with a visitor's browser (cross-site WebSocket hijacking).

Browsers always send an Origin header on a WebSocket handshake and a page cannot change it. Anything that is not one of our
own sites is refused. Clients that are not browsers send no Origin; they cannot be told apart from a script anyway, and the
sockets still demand a valid token (except the read-only public one).
"""

from fastapi import WebSocket

from app.core.config import allowed_origins


def origin_ok(ws: WebSocket) -> bool:
    origin = ws.headers.get("origin")
    return origin is None or origin.rstrip("/") in allowed_origins()


async def refuse_foreign(ws: WebSocket) -> bool:
    """Close the handshake (HTTP 403) and return True when the request came from another site."""
    if origin_ok(ws):
        return False
    await ws.close(code=1008)
    return True
