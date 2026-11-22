"""Many simultaneous WebSockets must not starve ordinary Redis commands (or each other)."""

import asyncio

import pytest

from app import realtime


async def test_hundreds_of_subscribers_do_not_exhaust_the_command_pool():
    subs = []
    try:
        # more than redis-py's default pool size of 100: one subscription per connected socket
        for _ in range(260):
            ps = realtime.new_pubsub()
            await ps.subscribe("room:pooltest")
            subs.append(ps)
        # ordinary commands (rate limits, presence, publishing) must still work meanwhile
        await asyncio.gather(*[realtime.client().incr(f"rl:pooltest:{i % 5}") for i in range(300)])
        await realtime.publish_room(0, {"type": "ping"})
        receivers = await realtime.client().publish("room:pooltest", "hello")
        assert receivers == 260  # every subscriber is attached and reachable
    finally:
        for ps in subs:
            await ps.aclose()
        await realtime.client().delete(*[f"rl:pooltest:{i}" for i in range(5)])


async def test_a_burst_of_commands_waits_for_a_free_connection_instead_of_failing():
    r = realtime.client()
    results = await asyncio.gather(*[r.ping() for _ in range(600)])  # far more than the pool holds
    assert all(results)


@pytest.mark.parametrize("module", ["app.routers.ws", "app.routers.ws_rooms", "app.routers.ws_me"])
def test_sockets_use_the_dedicated_subscription_pool(module):
    import importlib
    import inspect

    src = inspect.getsource(importlib.import_module(module))
    assert "client().pubsub()" not in src and "new_pubsub()" in src
