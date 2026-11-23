"""Editing rule sets safely: merge a change onto a copy, validate it, and describe what differs."""

import copy
from typing import Any

from app.engine.rules import DEFAULT_RULES, RuleConfig
from app.engine.standings import KNOWN_TIEBREAKERS, StandingsRules


def deep_merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective(cfg: dict[str, Any] | None) -> dict[str, Any]:
    """What the game actually uses: stored settings over the defaults (older rule sets are partial)."""
    return deep_merge(DEFAULT_RULES, cfg or {})


def _int(cfg: dict[str, Any], path: str, lo: int, hi: int, errors: list[str]) -> int | None:
    cur: Any = cfg
    for part in path.split("."):
        cur = cur.get(part) if isinstance(cur, dict) else None
    if isinstance(cur, bool) or not isinstance(cur, int) or not lo <= cur <= hi:
        errors.append(f"{path} must be a whole number from {lo} to {hi}")
        return None
    return cur


def validate(cfg: dict[str, Any]) -> list[str]:
    """Every reason this configuration is unusable (empty if it is fine)."""
    errors: list[str] = []
    unknown = set(cfg) - set(DEFAULT_RULES)
    if unknown:
        errors.append(f"unknown settings: {', '.join(sorted(unknown))}")
    overs = _int(cfg, "overs", 1, 20, errors)
    _int(cfg, "wickets", 1, 15, errors)
    _int(cfg, "balls_per_over", 1, 12, errors)
    _int(cfg, "players_per_team", 2, 15, errors)
    _int(cfg, "submission_seconds", 30, 1800, errors)
    _int(cfg, "umpire_duty_penalty", 0, 10, errors)
    _int(cfg, "dispute_window_hours", 1, 720, errors)
    _int(cfg, "toss_timeout_minutes", 1, 240, errors)
    _int(cfg, "normal_over.max_repeat_one_digit", 1, 6, errors)
    _int(cfg, "normal_over.max_repeat_other", 1, 6, errors)
    _int(cfg, "stats.min_balls_strike_rate", 1, 200, errors)
    _int(cfg, "stats.min_balls_economy", 1, 200, errors)
    mob = _int(cfg, "max_overs_per_bowler", 1, 20, errors)
    if overs and mob and mob > overs:
        errors.append("max_overs_per_bowler cannot exceed overs")
    for k in ("win", "tie", "loss", "walkover_win", "walkover_loss", "no_result", "abandoned"):
        _int(cfg, f"points.{k}", 0, 10, errors)
    if (cfg.get("knockout") or {}).get("qualifiers") not in (2, 4):
        errors.append("knockout.qualifiers must be 2 or 4")
    if (cfg.get("knockout") or {}).get("tie") != "higher_seed":
        errors.append("knockout.tie must be 'higher_seed'")
    order = cfg.get("tiebreakers")
    if not isinstance(order, list) or not order or not set(order) <= KNOWN_TIEBREAKERS or len(set(order)) != len(order):
        errors.append(f"tiebreakers must be a list of distinct names from {sorted(KNOWN_TIEBREAKERS)}")
    for k in ("bowling_pp_overs", "batting_pp_overs"):
        v = cfg.get(k)
        if not isinstance(v, list) or any(isinstance(x, bool) or not isinstance(x, int) or x < 1 or (overs and x > overs) for x in v):
            errors.append(f"{k} must be a list of over numbers within the match")
    if not errors:
        try:
            RuleConfig.from_dict(cfg)
            StandingsRules.from_config(cfg)
        except (KeyError, TypeError, ValueError) as e:
            errors.append(f"configuration is unusable: {e}")
    return errors


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, v in d.items():
            out.update(_flat(v, f"{prefix}{k}."))
        return out
    return {prefix.rstrip("."): d}


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
    a, b = _flat(old), _flat(new)
    return [{"path": p, "from": a.get(p), "to": b.get(p)} for p in sorted(set(a) | set(b)) if a.get(p) != b.get(p)]
