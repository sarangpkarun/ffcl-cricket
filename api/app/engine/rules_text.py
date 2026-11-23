"""The rules of a season in plain language, built from the rule set so it can never disagree with the game."""

from typing import Any

from app.engine.rules_admin import effective

TIEBREAK_TEXT = {"points": "points", "nrr": "net run rate", "wins": "number of wins",
                 "head_to_head": "results between the teams concerned", "name": "team name"}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _overs(nums: list[int]) -> str:
    return ", ".join(str(n) for n in nums) if nums else "none"


def summarize(config: dict[str, Any] | None) -> list[dict[str, Any]]:
    c = effective(config)
    pts = c["points"]
    normal = c["normal_over"]
    sections = [
        {"title": "The match", "items": [
            f"Each side has {c['players_per_team']} players and bats for {_plural(c['overs'], 'over')} of {c['balls_per_over']} balls.",
            f"An innings ends after {_plural(c['overs'], 'over')}, when {_plural(c['wickets'], 'wicket')} have fallen, or when the chasing side passes the target.",
            "The target is the first innings total plus one. Equal totals are a tie.",
            f"A bowler can bowl at most {_plural(c['max_overs_per_bowler'], 'over')}.",
        ]},
        {"title": "How a ball is played", "items": [
            f"For every over the batter and the bowler each choose {c['balls_per_over']} digits from 1 to 6, in secret. The umpire reveals both sets together.",
            "Ball by ball, the digits are compared. If they match, the batter is out. Otherwise the batter scores the number on their digit.",
            "Neither side, nor anyone watching, sees the digits before the umpire reveals them.",
        ]},
        {"title": "Over types", "items": [
            f"Normal overs: a bowler may use one digit up to {normal['max_repeat_one_digit']} times and every other digit at most {normal['max_repeat_other']} times.",
            f"Bowling powerplay (over {_overs(c['bowling_pp_overs'])}): the batter must use the digits 5 and 6 exactly once each; the other four are free.",
            f"Batting powerplay (over {_overs(c['batting_pp_overs'])}): the bowler must use the digits 5 and 6 exactly once each; the other four follow the normal limit.",
        ]},
        {"title": "Points and the table", "items": [
            f"A win earns {_plural(pts['win'], 'point')}, a tie {_plural(pts['tie'], 'point')} and a loss {_plural(pts['loss'], 'point')}.",
            f"If a team does not turn up, the other team is awarded the match ({_plural(pts['walkover_win'], 'point')}) and the absent team gets {_plural(pts['walkover_loss'], 'point')}. No scores are recorded.",
            f"A match that cannot be completed earns each team {_plural(pts['no_result'], 'point')} and does not affect net run rate.",
            "Teams level on points are separated by: " + ", then ".join(TIEBREAK_TEXT[t] for t in c["tiebreakers"]) + ".",
            "Net run rate is runs scored per over minus runs conceded per over. A side that is all out is counted as having faced its full overs.",
        ]},
        {"title": "Knockouts", "items": [
            f"The top {c['knockout']['qualifiers']} teams after the league go through" + (
                " to semi-finals (first v fourth, second v third) and a final." if c["knockout"]["qualifiers"] == 4
                else " to a final."),
            "A knockout match cannot end level: the team that finished higher in the league goes through.",
        ]},
        {"title": "Fair play", "items": [
            "The umpire can apply penalty runs or wickets to a team's total. Penalties never count towards a player's own figures.",
            f"If a captain has not answered the toss {_plural(c['toss_timeout_minutes'], 'minute')} after the scheduled start, the umpire may declare a walkover against that team. Nothing happens automatically, and an admin can reverse it.",
            f"A team that supplies an umpire loses {_plural(c['umpire_duty_penalty'], 'point')} if that umpire does not turn up.",
        ]},
    ]
    return sections
