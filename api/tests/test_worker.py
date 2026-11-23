from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import Match, Notification, Over
from app.services.reminders import purge_notifications, scan_deadlines, scan_reminders
from app.worker import WorkerSettings
from tests.helpers import run_toss, setup_match, start
from tests.ws_helpers import connect, next_of, token_of

NOW = datetime(2030, 6, 1, 18, 0, tzinfo=UTC)


def ctx_for(engine):
    return {"session_factory": async_sessionmaker(engine, expire_on_commit=False)}


async def set_start(db, match_id, when, status=None):
    values = {"scheduled_at": when}
    if status:
        values["status"] = status
    await db.execute(update(Match).where(Match.id == match_id).values(**values))
    await db.commit()


async def notes(db, kind):
    db.expire_all()
    return list(await db.scalars(select(Notification).where(Notification.kind == kind).order_by(Notification.id)))


# ---------- match reminders ----------
async def test_reminder_goes_to_everyone_in_the_match_once(make_user, db, engine):
    ctx = await setup_match(make_user)
    await set_start(db, ctx.match, NOW + timedelta(minutes=45))
    assert await scan_reminders(ctx_for(engine), now=NOW) == {"match_reminder": 9, "toss_reminder": 0}  # 8 players + umpire
    got = await notes(db, "match_reminder")
    assert {n.user_id for n in got} == {p.id for p in ctx.a + ctx.b} | {ctx.ump.id}
    assert got[0].title == "Match 1 starts in 45 min" and got[0].body == "Pink vs Green"
    assert got[0].data["link"] == f"/matches/{ctx.match}"
    assert await scan_reminders(ctx_for(engine), now=NOW + timedelta(minutes=2)) == {"match_reminder": 0, "toss_reminder": 0}


async def test_second_reminder_follows_the_first(make_user, db, engine):
    ctx = await setup_match(make_user)
    await set_start(db, ctx.match, NOW + timedelta(minutes=55))
    await scan_reminders(ctx_for(engine), now=NOW)
    await scan_reminders(ctx_for(engine), now=NOW + timedelta(minutes=46))  # 9 minutes to go
    got = await notes(db, "match_reminder")
    assert sorted({n.title for n in got}) == ["Match 1 starts in 55 min", "Match 1 starts in 9 min"]
    assert len(got) == 18


async def test_a_match_created_late_only_gets_the_reminder_that_still_makes_sense(make_user, db, engine):
    ctx = await setup_match(make_user)
    await set_start(db, ctx.match, NOW + timedelta(minutes=8))
    await scan_reminders(ctx_for(engine), now=NOW)
    assert {n.title for n in await notes(db, "match_reminder")} == {"Match 1 starts in 8 min"}


async def test_no_reminders_when_nothing_is_due(make_user, db, engine):
    ctx = await setup_match(make_user)
    c = ctx_for(engine)
    await set_start(db, ctx.match, NOW + timedelta(hours=3))  # too far away
    assert await scan_reminders(c, now=NOW) == {"match_reminder": 0, "toss_reminder": 0}
    await set_start(db, ctx.match, None)  # unscheduled
    assert await scan_reminders(c, now=NOW) == {"match_reminder": 0, "toss_reminder": 0}
    await set_start(db, ctx.match, NOW + timedelta(minutes=30), status="toss")  # already under way
    assert await scan_reminders(c, now=NOW) == {"match_reminder": 0, "toss_reminder": 0}
    assert await notes(db, "match_reminder") == []


async def test_toss_reminder_goes_to_captains_and_umpire_only_once(make_user, db, engine):
    ctx = await setup_match(make_user)
    c = ctx_for(engine)
    await set_start(db, ctx.match, NOW - timedelta(minutes=5))
    assert (await scan_reminders(c, now=NOW))["toss_reminder"] == 3
    assert {n.user_id for n in await notes(db, "toss_reminder")} == {ctx.a[0].id, ctx.b[0].id, ctx.ump.id}
    assert (await scan_reminders(c, now=NOW + timedelta(minutes=1)))["toss_reminder"] == 0
    # nobody is nagged about a match that is hours overdue
    ctx2 = await setup_match(make_user)
    await set_start(db, ctx2.match, NOW - timedelta(hours=4))
    assert (await scan_reminders(c, now=NOW))["toss_reminder"] == 0


async def test_reminders_respect_preferences(make_user, db, engine):
    ctx = await setup_match(make_user)
    quiet = ctx.a[2]
    await quiet.req("PUT", "/notifications/prefs", json={"kind": "match_reminder", "in_app": False})
    await set_start(db, ctx.match, NOW + timedelta(minutes=30))
    await scan_reminders(ctx_for(engine), now=NOW)
    ids = {n.user_id for n in await notes(db, "match_reminder")}
    assert quiet.id not in ids and ctx.a[1].id in ids


# ---------- deadline alert ----------
async def open_over(ctx, batters, bowlers):
    await ctx.ump.req("POST", f"{ctx.url}/overs/start", json={"bowler_id": bowlers[0].id, "batter_id": batters[0].id})
    await ctx.ump.req("POST", f"{ctx.url}/overs/current/signal")
    return bowlers[0], batters[0]


async def set_deadline(db, when):
    await db.execute(update(Over).values(deadline_at=when))
    await db.commit()


async def test_deadline_alert_goes_only_to_whoever_has_not_submitted(make_user, db, engine):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = await open_over(ctx, batters, bowlers)
    await bowler.req("POST", f"{ctx.url}/overs/current/submit", json={"digits": "652143"})
    await set_deadline(db, NOW + timedelta(seconds=25))
    assert await scan_deadlines(ctx_for(engine), now=NOW) == 1
    got = await notes(db, "deadline_alert")
    assert [n.user_id for n in got] == [batter.id] and got[0].title == "About 30 seconds left"
    assert await scan_deadlines(ctx_for(engine), now=NOW + timedelta(seconds=5)) == 0  # once per over


async def test_deadline_alert_covers_both_when_neither_submitted(make_user, db, engine):
    ctx = await setup_match(make_user)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    bowler, batter = await open_over(ctx, batters, bowlers)
    await set_deadline(db, NOW + timedelta(seconds=20))
    assert await scan_deadlines(ctx_for(engine), now=NOW) == 2
    assert {n.user_id for n in await notes(db, "deadline_alert")} == {bowler.id, batter.id}


async def test_no_deadline_alert_when_it_is_not_close_or_not_relevant(make_user, db, engine):
    ctx = await setup_match(make_user)
    c = ctx_for(engine)
    batters, bowlers = await run_toss(ctx, "a", "bat")
    await start(ctx)
    await open_over(ctx, batters, bowlers)
    await set_deadline(db, NOW + timedelta(minutes=3))  # plenty of time
    assert await scan_deadlines(c, now=NOW) == 0
    await set_deadline(db, NOW - timedelta(seconds=1))  # already past
    assert await scan_deadlines(c, now=NOW) == 0
    await set_deadline(db, NOW + timedelta(seconds=20))
    await ctx.ump.req("POST", f"{ctx.url}/pause")  # paused: the clock is not the players' fault
    assert await scan_deadlines(c, now=NOW) == 0
    await ctx.ump.req("POST", f"{ctx.url}/resume")
    assert await scan_deadlines(c, now=NOW) == 2
    # once submissions are locked there is nothing to warn about
    ctx2 = await setup_match(make_user)
    b2, w2 = await run_toss(ctx2, "a", "bat")
    await start(ctx2)
    bowler2, batter2 = await open_over(ctx2, b2, w2)
    for p, d in ((bowler2, "652143"), (batter2, "561234")):
        await p.req("POST", f"{ctx2.url}/overs/current/submit", json={"digits": d})
    await ctx2.ump.req("POST", f"{ctx2.url}/overs/current/lock")
    await db.execute(update(Over).where(Over.state == "locked").values(deadline_at=NOW + timedelta(seconds=10)))
    await db.commit()
    before = len(await notes(db, "deadline_alert"))
    await scan_deadlines(c, now=NOW)
    assert len(await notes(db, "deadline_alert")) == before


# ---------- housekeeping + wiring ----------
async def test_purge_keeps_recent_and_unread(make_user, db, engine):
    p = await make_user("P")
    old = datetime.now(UTC) - timedelta(days=100)
    ancient = datetime.now(UTC) - timedelta(days=400)
    db.add_all([
        Notification(user_id=p.id, kind="result", title="old read", dedupe_key="a", created_at=old, read_at=old),
        Notification(user_id=p.id, kind="result", title="old unread", dedupe_key="b", created_at=old),
        Notification(user_id=p.id, kind="result", title="ancient unread", dedupe_key="c", created_at=ancient),
        Notification(user_id=p.id, kind="result", title="fresh read", dedupe_key="d", read_at=datetime.now(UTC)),
    ])
    await db.commit()
    assert await purge_notifications(ctx_for(engine)) == 2
    left = {n.title for n in await db.scalars(select(Notification).where(Notification.user_id == p.id))}
    assert left == {"old unread", "fresh read"}


def test_worker_is_wired_correctly():
    names = {j.name for j in WorkerSettings.cron_jobs}
    assert {"cron:scan_reminders", "cron:scan_deadlines", "cron:purge_notifications", "cron:purge_dead_subscriptions"} <= names
    assert {f.__name__ for f in WorkerSettings.functions} == {
        "scan_reminders", "scan_deadlines", "purge_notifications", "send_push", "purge_dead_subscriptions"}
    assert WorkerSettings.redis_settings.host


async def test_scheduled_notifications_are_pushed_live(make_user, db, engine, ws_url):
    ctx = await setup_match(make_user)
    await set_start(db, ctx.match, NOW + timedelta(minutes=30))
    async with await connect(f"{ws_url}/ws/me", token_of(ctx.a[1])) as w:
        await next_of(w, "hello")
        await scan_reminders(ctx_for(engine), now=NOW)
        ev = await next_of(w, "notification")
        assert ev["notification"]["kind"] == "match_reminder" and ev["notification"]["title"].startswith("Match 1 starts in")
