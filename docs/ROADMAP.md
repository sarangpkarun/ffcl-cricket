# FFCL Platform: Roadmap

## Context
FFCL is a digit-based cricket league currently run over WhatsApp. This roadmap covers building a mobile-responsive web app (with database) that automates the game: registration, teams, toss, 7-over digit game, umpire control, live scorecards, match and tournament chat, fixtures, points table and stats. Goal: make the game playable first (Phase 1), then expand to a full tournament platform.

**Deliverable on approval:** write this content to `/home/sarang/Documents/FFCL/ROADMAP.md`.

## Tech stack
| Layer | Choice |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind, shadcn/ui (mobile-first, PWA later) |
| Backend | FastAPI (REST + WebSockets) |
| DB | PostgreSQL (source of truth), SQLAlchemy + Alembic migrations |
| Cache / pub-sub | Redis (live state, WS fan-out, rate limits) |
| Jobs | ARQ (or Celery): reminders, deadlines, notifications |
| Auth | JWT + refresh, OTP mobile verification, RBAC |
| Storage | S3 / MinIO (avatars, logos, chat media) |
| Deploy | Docker Compose, Nginx, AWS EC2, GitHub Actions CI |

Key principles:
- Postgres is authoritative; Redis never the only copy of scores or submissions.
- Append-only `ball_events` and `penalties`; scorecards are derived and can be recomputed after umpire corrections.
- Rules are data (versioned config), not hardcoded; the engine is pure and unit-testable.
- Unique constraints plus transactions prevent duplicate ball scoring and duplicate penalties.
- Hidden digits are never sent to the opposing client before reveal (enforced server-side).

## Open decisions (resolve in Phase 0; all configurable in rule config)
1. Same digit (e.g. 3-3, 5-5): does the bowler get wicket credit, or team wicket only?
2. Normal-over bowling limit: each digit max 3 times, vs exactly 3 if used. Clarify the conflicting rulebook example.
3. Submission flow: both private and umpire reveals together, vs bowler first then batter, vs shared after signal. Build the flow as a configurable state machine.
4. Multiple simultaneous matches: assume yes (design all state per match).
5. Scoring table: confirm the batter/bowler digit to runs rule (examples show 2/5 gives 2, 4/1 gives 4, 6/3 gives 6; equal digits give a wicket).

## Phase 0: Foundations (week 1-2)
- Finalise rulebook decisions above; write `RULES.md` with worked examples that become test cases.
- Repo setup (monorepo: `web/`, `api/`, `infra/`), Docker Compose (api, web, postgres, redis, minio), CI (lint, test, build).
- Design system and mobile-first layout shell; role-based nav (Home, Matches, Chat, Profile).
- DB schema v1 + Alembic: users, roles, seasons, teams, team_members, matches, match_players, tosses, innings, overs, ball_events, digit_submissions, penalties, audit_logs, rule_sets.
- **Exit:** `docker compose up` runs an empty app with a health check and a migrated DB.

## Phase 1: Core MVP, a playable match (week 3-9)
1. **Auth and profiles:** email/password login, OTP mobile verify, unique player ID, registered-number enforcement, multi-role RBAC, session management, logout-all.
2. **Seasons, teams, players:** season CRUD, team CRUD (name, logo, colours), captain/vice-captain, roster approval, max 7 players.
3. **Match setup:** create match (teams, time, umpire), lineup (Playing XI), max 2 overs per bowler validation.
4. **Toss:** captain toss selection, winner chooses bat/bowl, timeout and default per rulebook, umpire confirmation.
5. **Game engine** (pure Python module, heavily unit-tested):
   - Over config (7 overs; over 2 bowling PP, over 6 batting PP; digit limits).
   - Digit validation (1-6 only, six digits, PP rules, per-digit cap).
   - Ball resolution (runs, wickets), legal balls/overs, target, all-out, win/tie detection.
   - Penalty runs/wickets go to team totals only, never individual stats.
6. **Digit submission UI:** mobile keypad 1-6, six slots, clear/edit, confirm, lock, deadline, private visibility, timestamps; idempotent server submit.
7. **Umpire dashboard:** open match, signal, open/lock submissions, reveal, confirm wicket, apply penalty, correct entries (with audit log), pause/resume, end innings, declare result.
8. **Live scorecard:** team and batting/bowling tables; WebSocket updates (basic).
9. **Match result** and innings break with target.
- **Exit:** a full 7-over match can be played end to end on phones with an umpire, with correct scoring verified against real past WhatsApp matches.

## Phase 2: Real-time communication (week 10-13)
- WebSocket gateway (Redis pub/sub), reconnect and resync, presence, typing indicators.
- Tournament room chat: text, emoji, images/stickers, replies, reactions, @mentions, edit/delete, pins, announcements, read receipts, search, report.
- Per-match chat auto-created; access limited to participants and officials; history kept after the match.
- Three channels per match: match chat, umpire channel (umpire and admins), private submissions (kept separate from chat).
- System messages (toss, innings start, wicket, penalty, result), visually distinct.
- Moderation tools, in-app notifications, notification preferences.
- **Exit:** a match runs entirely in-app, replacing the WhatsApp group.

## Phase 3: Tournament management (week 14-17)
- Fixtures (group and knockout), publish and schedule, umpire assignment and duty records (lose 1 point if duty is skipped).
- Points table: configurable win/loss/tie/walkover points, NRR, tie-breakers.
- Season and player stats, leaderboards (runs, wickets, SR, economy, 4s/6s, POTM, win %), filters by season/team/player.
- Walkover and abandonment management, team replacement and number-change approvals, season archive and history.
- Admin dashboard: users, seasons, teams, matches, rules (versioned), audit log viewer, reports and exports.
- **Exit:** a full season can be run and standings are auto-computed.

## Phase 4: Public site and polish (week 18-22)
- Public pages (no login): home, current season, teams, players, fixtures, live matches, points, results, stats, history, rules.
- PWA install, browser push, optional email; WhatsApp integration hook (future).
- Dispute and complaint management, advanced analytics, exportable scorecards (PDF/image), match highlights.
- Multi-tournament support; accessibility, performance and SEO pass.

## Phase 5: Hardening and launch (parallel, final 2-3 weeks)
- Load test (many concurrent matches and chat), WS reconnect and chaos tests, backups and restore drill.
- Security: rate limiting, OTP abuse protection, input sanitising, media moderation, secrets management, OWASP review.
- Monitoring (Sentry, logs, metrics), staging environment, UAT with real FFCL teams, pilot on one live season round, then full cutover.

## Edge cases checklist (test in Phases 1-2)
Simultaneous or duplicate submissions; disconnect mid-submission; late submissions; both submit before the signal; umpire disconnect; result correction and replay; pause/resume; all-out; target reached early; tie; walkover; missing player; unregistered number; third over for a bowler; duplicate penalty; chat arriving during score update.

## Risks
| Risk | Mitigation |
|---|---|
| Rule ambiguity | Resolve in Phase 0; rules configurable and versioned |
| Real-time desync | Server-authoritative state, event sequence numbers, resync on reconnect |
| Digit leakage | Server-side visibility filtering; never broadcast hidden digits |
| Scope creep | Strict phase gates; MVP is playable before chat |
| Umpire workload | Dashboard defaults, keyboard/mobile shortcuts, undo via corrections |

## Verification
- Engine: table-driven unit tests from rulebook examples (over types, digit limits, scoring, penalties, win/tie).
- API: integration tests with real Postgres/Redis (submit race, duplicate ball, duplicate penalty).
- E2E (Playwright, mobile viewport): player A/B plus umpire complete a match; spectator sees live updates; opponent cannot see hidden digits.
- Replay test: re-derive scorecards from `ball_events` and compare after a correction.
- Pilot: shadow a real FFCL match against the WhatsApp result.
