import json

from tests.helpers import live, play, run_toss, setup_match, start
from tests.ws_helpers import closed_with, connect, next_change, recv, token_of


async def test_socket_requires_valid_token(make_user, ws_url):
    ctx = await setup_match(make_user)
    url = f"{ws_url}/ws/matches/{ctx.match}"
    assert await closed_with(url, token="garbage") == 4401
    assert await closed_with(url, first_message="not json") == 4401
    assert await closed_with(url, first_message=json.dumps({"type": "hello"})) == 4401
    assert await closed_with(f"{ws_url}/ws/matches/999999", token=token_of(ctx.a[0])) == 4404
    # a token in the query string is ignored: it must come in the first message
    assert await closed_with(f"{url}?token={token_of(ctx.a[0])}") == 4401


async def test_silent_connection_is_dropped(make_user, ws_url, monkeypatch):
    from app.routers import ws as ws_mod

    monkeypatch.setattr(ws_mod, "AUTH_TIMEOUT_SECONDS", 0.3)
    ctx = await setup_match(make_user)
    assert await closed_with(f"{ws_url}/ws/matches/{ctx.match}") == 4401


async def test_logged_out_session_cannot_connect(make_user, ws_url):
    ctx = await setup_match(make_user)
    p = ctx.a[1]
    tok = token_of(p)
    await p.req("POST", "/auth/logout-all")
    assert await closed_with(f"{ws_url}/ws/matches/{ctx.match}", token=tok) == 4401


async def test_watchers_get_changes_without_any_digits(make_user, ws_url):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    fan = await make_user("Fan")
    url = f"{ws_url}/ws/matches/{ctx.match}"
    w_fan, w_bat = await connect(url, token_of(fan)), await connect(url, token_of(batters[0]))
    async with w_fan, w_bat:
        hello = await recv(w_fan)
        assert hello["type"] == "hello" and hello["seq"] == (await live(ctx))["match"]["seq"]
        await recv(w_bat)
        bowler, batter = bowlers[0], batters[0]
        await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowler.id, "batter_id": batter.id})
        await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
        await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "654321"})
        seqs = []
        for w in (w_fan, w_bat):
            msgs = []
            while len(msgs) < 3:
                msgs.append(await next_change(w))
            seqs.append([m["seq"] for m in msgs])
            for m in msgs:
                assert set(m) == {"type", "seq"}  # nothing but a sequence number is ever broadcast
        assert seqs[0] == seqs[1] and seqs[0] == sorted(seqs[0]) and len(set(seqs[0])) == 3
        assert seqs[0][-1] == (await live(ctx))["match"]["seq"]


async def test_every_stage_of_an_over_notifies(make_user, ws_url):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    fan = await make_user("Fan")
    async with await connect(f"{ws_url}/ws/matches/{ctx.match}", token_of(fan)) as w:
        await recv(w)
        await play(ctx, batters, bowlers, 1)
        got = []
        while True:
            try:
                got.append((await next_change(w, timeout=1))["seq"])
            except TimeoutError:
                break
        # start, signal, 2 submits, lock, reveal, resolve
        assert len(got) == 7 and got[-1] == (await live(ctx))["match"]["seq"]


async def test_publish_failure_does_not_break_requests(make_user, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "redis_url", "redis://127.0.0.1:1/0")
    from app import realtime

    realtime._clients.clear()
    ctx = await setup_match(make_user)  # lineup edits publish; must still succeed
    assert (await ctx.ump.req("POST", f"{ctx.url}/toss/open")).status_code == 204
    realtime._clients.clear()
