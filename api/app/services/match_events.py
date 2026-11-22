"""What the app announces (system chat messages + notifications) for each match event.

Called inside the same transaction as the state change. Texts must never contain digits that
are still hidden: everything here runs after the umpire's reveal or does not mention digits.
"""

from app.db.models import Innings, Match, Over, Penalty, Team
from app.engine import Ball, RuleConfig
from app.services import announce
from app.services.announce import match_audience, say, team_audience, team_names, user_names
from app.services.notify import notify
from app.services.outbox import queue_room_state
from app.services.scoring import Recomputed, get_innings


def _link(m: Match) -> dict:
    return {"match_id": m.id, "link": f"/matches/{m.id}"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


async def toss_opened(db, m: Match) -> None:
    names = await team_names(db, m)
    captains = set()
    for tid in (m.team_a_id, m.team_b_id):
        t = await db.get(Team, tid)
        if t and t.captain_id:
            captains.add(t.captain_id)
    await notify(db, captains, "toss_ready", "The toss is open",
                 f"{names[m.team_a_id]} vs {names[m.team_b_id]}: the umpire is ready for the toss.",
                 _link(m), f"toss:{m.id}")


async def toss_confirmed(db, m: Match, winner_id: int, decision: str) -> None:
    names = await team_names(db, m)
    await say(db, m, f"🪙 Toss won by {names[winner_id]}.")
    await say(db, m, f"🏏 {names[winner_id]} elected to {'bat' if decision == 'bat' else 'bowl'} first.")


async def innings_started(db, m: Match, inn: Innings) -> None:
    names = await team_names(db, m)
    if inn.number == 1:
        await say(db, m, f"🎾 First innings started. {names[inn.batting_team_id]} are batting.")
    else:
        await say(db, m, f"🎾 Second innings started. {names[inn.batting_team_id]} need {inn.target} to win.")


async def paused(db, m: Match, is_paused: bool) -> None:
    await say(db, m, "⏸ The match is paused by the umpire." if is_paused else "▶ The match has resumed.")


async def over_signalled(db, m: Match, inn: Innings, over: Over) -> None:
    who = await user_names(db, {over.bowler_id, over.batter_id})
    note = {"bowling_pp": " ⚡ Bowling powerplay: the batter must use 5 and 6 once each.",
            "batting_pp": " ⚡ Batting powerplay: the bowler must use 5 and 6 once each."}.get(over.over_type, "")
    await say(db, m, f"🔔 Over {over.number}: {who.get(over.bowler_id or 0)} bowls to {who.get(over.batter_id or 0)}. "
                     f"Submissions are open.{note}")
    pair = {i for i in (over.bowler_id, over.batter_id) if i}
    await notify(db, pair, "your_over", f"Over {over.number}: submit your digits now",
                 "Open the match and enter your six digits before the deadline.", _link(m), f"over:{over.id}")
    queue_room_state(db, (await announce.rooms(db, m))["match"].id)  # the chat lock switches on for the pair


async def over_locked(db, m: Match) -> None:
    queue_room_state(db, (await announce.rooms(db, m))["match"].id)  # chat opens up again


async def over_resolved(db, m: Match, inn: Innings, over: Over, balls: list[Ball], rec: Recomputed | None,
                        prev_status: str, prev_result: str | None, rules: RuleConfig) -> None:
    who = await user_names(db, {over.bowler_id, over.batter_id})
    batter = who.get(over.batter_id or 0) or "The batter"
    for b in balls:
        spot = f"{b.over_no}.{b.ball_no}"
        if b.wicket:
            await say(db, m, f"❌ {batter} is OUT ({spot}).")
        elif b.runs == 6:
            await say(db, m, f"🔥 {batter} scored 6 runs ({spot}).")
    summary = None
    if rec:
        s = rec.first if inn.number == 1 else rec.second
        if s:
            names = await team_names(db, m)
            runs = sum(b.runs for b in balls)
            wk = sum(1 for b in balls if b.wicket)
            summary = (f"Over {over.number} done: {_plural(runs, 'run')}, {_plural(wk, 'wicket')}. "
                       f"{names[inn.batting_team_id]} {s.runs}/{s.wickets} ({s.overs_text} ov).")
            await say(db, m, f"📊 {summary}")
            if wk:
                await notify(db, await team_audience(db, m, inn.batting_team_id), "wicket",
                             f"Wicket in over {over.number}", summary, _link(m), f"wkt:{over.id}")
            await notify(db, await match_audience(db, m), "over_complete", f"Over {over.number} finished",
                         summary, _link(m), f"over-done:{over.id}")
    await status_changed(db, m, rec, prev_status, prev_result)


async def status_changed(db, m: Match, rec: Recomputed | None, prev_status: str, prev_result: str | None) -> None:
    """Innings break, final result, and changes to either caused by penalties or corrections."""
    if rec is None:
        return
    inns = await get_innings(db, m.id)
    names = await team_names(db, m)
    if prev_status == "innings1" and m.status == "break":
        s1 = rec.first
        await say(db, m, f"🏁 {names[inns[0].batting_team_id]} finished on {s1.runs}/{s1.wickets} ({s1.overs_text} ov). "
                         f"{names[inns[1].batting_team_id]} need {inns[1].target} to win.")
    if m.status == "completed" and prev_status != "completed":
        await say(db, m, f"🏆 {m.result_text}")
        await notify(db, await match_audience(db, m), "result", "Match result", m.result_text, _link(m), f"result:{m.id}:1")
    elif m.status == "completed" and prev_result and m.result_text != prev_result:
        await say(db, m, f"🛠 Result updated: {m.result_text}")
        await notify(db, await match_audience(db, m), "result", "Match result updated", m.result_text,
                     _link(m), f"result:{m.id}:{abs(hash(m.result_text)) % 10**8}")
    elif prev_status == "completed" and m.status != "completed":
        await say(db, m, "🛠 The result was withdrawn after a correction. The match continues.")


async def penalty_applied(db, m: Match, pen: Penalty, umpire_name: str) -> None:
    names = await team_names(db, m)
    team = names[pen.team_id]
    parts = []
    if pen.runs:
        parts.append(f"{abs(pen.runs)} penalty run{'' if abs(pen.runs) == 1 else 's'} "
                     f"{'awarded to' if pen.runs > 0 else 'deducted from'} {team}")
    if pen.wickets:
        parts.append(f"{_plural(pen.wickets, 'penalty wicket')} charged to {team}")
    text = " and ".join(parts)
    await say(db, m, f"📢 {text}: {pen.reason}.")
    await say(db, m, f"📢 {umpire_name} applied penalty '{pen.kind}' to {team} "
                     f"(runs {pen.runs:+d}, wickets {pen.wickets}). Reason: {pen.reason}", to="umpire")
    await notify(db, await team_audience(db, m, pen.team_id), "penalty", "Penalty applied", text, _link(m), f"pen:{pen.id}")


async def penalty_voided(db, m: Match, pen: Penalty, umpire_name: str, reason: str) -> None:
    names = await team_names(db, m)
    await say(db, m, f"📢 A penalty against {names[pen.team_id]} was cancelled by the umpire.")
    await say(db, m, f"📢 {umpire_name} cancelled penalty #{pen.id} ({pen.kind}) against {names[pen.team_id]}. "
                     f"Reason: {reason}", to="umpire")


async def digits_overridden(db, m: Match, over: Over, role: str, umpire_name: str, reason: str) -> None:
    label = "bowler" if role == "bowl" else "batter"
    await say(db, m, f"✍️ {umpire_name} entered the {label}'s digits for over {over.number} on their behalf. "
                     f"Reason: {reason}", to="umpire")


async def ball_corrected(db, m: Match, innings_no: int, over_no: int, ball_no: int, before: dict, after: dict,
                         umpire_name: str, reason: str) -> None:
    await say(db, m, f"🛠 The umpire corrected a ball (innings {innings_no}, over {over_no}.{ball_no}).")
    await say(db, m, f"🛠 {umpire_name} corrected innings {innings_no}, over {over_no}, ball {ball_no}: "
                     f"{before['runs']} run(s){' (wicket)' if before['wicket'] else ''} → "
                     f"{after['runs']} run(s){' (wicket)' if after['wicket'] else ''}. Reason: {reason}", to="umpire")


async def umpire_assigned(db, m: Match, umpire_id: int) -> None:
    names = await team_names(db, m)
    await notify(db, {umpire_id}, "umpire_assigned", f"You are the umpire for Match {m.match_no}",
                 f"{names[m.team_a_id]} vs {names[m.team_b_id]}", _link(m), f"umpire:{m.id}:{umpire_id}")
