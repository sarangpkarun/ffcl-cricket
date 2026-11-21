# FFCL Phase 1: Core MVP Plan (a playable match)

**Goal:** a full 7-over match played end to end on phones by two teams and an umpire, with automatic validation and scoring and a live scorecard. No chat, fixtures or points table yet (Phases 2-3).

**Duration:** about 9 weeks (Sprint 0 foundations, then 4 build sprints).

## Locked decisions (stored as rule config, not hardcoded)
| Decision | Default |
|---|---|
| Same digit (3-3, 5-5) | Wicket; bowler gets credit |
| Normal-over bowling limit | Only one digit may appear 3 times; no digit more than 3. Other digits: max 2 (confirmed). |
| Submission flow | Both submit privately; umpire locks and reveals together |
| Simultaneous matches | Supported (all state keyed by match) |
| Runs | Batter digit = runs, unless equal to bowler digit (wicket). **Confirm with rulebook in Sprint 0.** |
| Over types | 1,3,4,5,7 normal; 2 bowling PP (the BATTER must use 5 and 6 once each); 6 batting PP (the BOWLER must use 5 and 6 once each) |
| Match size | 7 overs, 7 wickets, max 2 overs per bowler, max 7 players per team |

These live in a `rule_sets` table (JSON, versioned). Each match pins a rule-set version.

## Scope
**In:** auth + OTP, profiles, roles, seasons, teams, roster, match creation, lineup, toss, game engine, digit submission, umpire dashboard, live scorecard (WebSocket), result, audit log for corrections, basic penalties.
**Out (later):** chat, notifications beyond in-app toasts, fixtures/points/leaderboards, public site, PWA push.

## Sprint 0: Foundations (week 1-2)
1. Write `RULES.md` with 20+ worked examples (each becomes a unit test). Confirm the runs rule and all-out/tie/target behaviour.
2. Monorepo: `api/` (FastAPI), `web/` (Next.js + TS + Tailwind + shadcn/ui), `infra/` (docker-compose: api, web, postgres, redis).
3. CI: lint, type-check, pytest, web build.
4. Alembic migration v1 (see schema below).
5. Mobile-first layout shell (bottom nav: Home, Matches, Profile), theme, shared components (digit keypad, score header).
- **Exit:** `docker compose up` shows an empty app, `/health` OK, migrations apply cleanly.

## Schema (Phase 1 tables)
`users`, `user_roles`, `otp_codes`, `sessions`, `seasons`, `teams`, `team_members`, `rule_sets`, `matches`, `match_players`, `tosses`, `innings`, `overs`, `digit_submissions`, `ball_events`, `penalties`, `audit_logs`.

Critical constraints:
- `ball_events` UNIQUE(innings_id, over_no, ball_no, revision): append-only; corrections add a new revision, never update.
- `digit_submissions` UNIQUE(over_id, role) with `locked_at`; one submission per role per over.
- `penalties` UNIQUE(match_id, idempotency_key).
- `users.phone` unique and verified; number change only via an approval record.
- Scorecards are derived from the latest revision of events plus penalties (view or computed service).

## Sprint 1: Identity and setup (week 3-4)
**Backend**
- Register/login (email+password, argon2), JWT access + refresh, logout-all (session revocation), OTP verify (provider behind an interface; console provider in dev).
- RBAC dependency (`require_role`), multi-role users, unique player ID generation.
- CRUD: seasons, teams (name, logo, colours), roster add/remove with approval, captain/vice-captain, max 7 cap.
- Match create (teams, time, umpire), lineup selection (Playing XI).

**Frontend:** login/register/OTP screens, profile, admin pages for seasons/teams/matches, captain lineup screen.

**Tests:** auth flows, role gating, roster cap, phone uniqueness.

## Sprint 2: Game engine (week 5-6, can start in Sprint 1 in parallel)
Pure Python package `api/app/engine/` with no DB or HTTP imports.
- `rules.py`: load rule config; over type lookup.
- `validate.py`: bowling digits (1-6 only, six digits, max 3 per digit on normal overs, PP: 5 and 6 once each; normal overs: at most one digit used 3 times, rest capped per rule config), batting digits (1-6, six; PP constraints on the correct side), return structured error codes.
- `resolve.py`: ball resolution (runs/wicket, bowler credit), over resolution.
- `state.py`: innings state reducer: score, wickets, legal balls, overs, extras/penalties, target, all-out, win/tie/chase-complete detection.
- `stats.py`: batting/bowling stats from events (penalties excluded from individual stats).
- Property tests: replaying events always yields the same state; penalties never alter player stats.
- **Exit:** 100% of `RULES.md` examples pass; engine coverage >95%.

## Sprint 3: Match flow, submission, umpire (week 6-8)
**Match state machine** (server-authoritative, persisted): `scheduled → toss → ready → innings1 → break → innings2 → completed` plus `paused`. Over sub-states: `awaiting_signal → submissions_open → locked → revealed → resolved`.

**Toss:** captain picks side, winner chooses bat/bowl, timeout default, umpire confirms.

**Submission API:**
- `POST /matches/{id}/overs/{n}/submit` validates via engine, rejects unregistered number/wrong role/closed window/late deadline, idempotent, locks on confirm.
- A visibility filter ensures the opponent and spectators never receive hidden digits before reveal (test this explicitly).
- Umpire sees only "submitted/not submitted" until lock, then reveals.

**Umpire dashboard (mobile friendly):** assigned matches, verify players, start match, send signal, open/lock/reveal, resolve over (one transaction writes six ball events), apply penalty (reason required), correct entry (reason required, audit-logged, new event revision), pause/resume, end innings, declare result.

**Transactions:** resolve-over and penalty-apply run in a single DB transaction with row lock on the match.

**Frontend:** player submission screen (keypad 1-6, six slots, clear/edit, confirm, lock, countdown), umpire console.

## Sprint 4: Live scorecard, result, hardening (week 8-9)
- WebSocket endpoint per match (`/ws/matches/{id}`) with Redis pub/sub; events: `over_resolved`, `penalty`, `state_changed`; client resync via `GET /matches/{id}/scorecard` on reconnect (sequence numbers).
- Live scorecard UI: team totals, run rate, required rate, target, batting and bowling tables, over-by-over timeline.
- Innings break (auto target), match result (win by wickets or runs, tie), final scorecard.
- Edge-case pass (see list), load test of ~10 simultaneous matches, bug bash with real players.

## Edge cases to test in Phase 1
Duplicate submit; simultaneous submits; submit before signal; submit after deadline; invalid digits (0, 7, wrong count, over-limit, PP violation); wrong phone/unregistered player; third over for a bowler; all out; target reached early; tie; pause/resume; umpire correction then scorecard replay; duplicate penalty; page refresh and reconnect mid-over.

## Verification
- `pytest`: engine unit tests, API integration tests against real Postgres/Redis (docker).
- Playwright (mobile viewport): two players plus umpire play a full 7-over match; assert opponent cannot read hidden digits via UI or API; spectator sees live updates.
- Replay test: rebuild scorecard from `ball_events` after a correction and compare.
- Shadow pilot: replay a past WhatsApp match's digits and compare final score.

## Definition of done
- A full match completes with correct scoring and result on mobile browsers.
- All correction and penalty actions are audit-logged.
- CI green; staging deployed via docker compose.
- Rules changeable via `rule_sets` without code changes.
