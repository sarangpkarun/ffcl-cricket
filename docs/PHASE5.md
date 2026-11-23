# FFCL Phase 5: Launch readiness of the app (plan)

## Context
Phases 1 to 4 built the whole product. Before real teams use it, a few things inside the app itself are still missing or unsafe: phone verification cannot work in production (the OTP code is printed to the server log, and players need a verified number to be put in a lineup), one rule is missing (what happens when a captain never answers the toss), players can only join by registering one at a time, and the security notes still list several "accepted for now" items. **This phase closes those, and nothing else.** Deployment, HTTPS, monitoring, backups and the pilot are yours to do later; they are listed in a short checklist at the end so nothing is forgotten, and none of it is built here.

What already exists and is reused: the OTP interface (`core/otp.py`), rate limiting (`services/ratelimit.py`, `routers/auth.py::throttle`), the walkover flow (`services/declarations.py::declare_walkover`), the rule set and its validation (`engine/rules.py`, `engine/rules_admin.py`), the approvals pattern (`routers/phone_changes.py`, `routers/roster.py`), the audit log, season scoping (`deps.py`), the worker (`worker.py`), the startup guard (`core/config.py::assert_production_safe`), the test helpers and the browser suite.

## Decisions
Answered by you:
| Question | Decision |
|---|---|
| Scope | **App-level items only.** No deployment, monitoring, backups, proxy config or pilot work in this phase. |
| Phone verification | **No SMS for the pilot: admins verify numbers.** The OTP interface and its abuse protections stay, with a "disabled" mode for production and a mock for tests; a real provider can be plugged in later. |
| Toss timeout (the last open rule) | **The umpire may declare a walkover after a wait.** After a configurable wait (default 15 minutes after the scheduled start) a "captain absent" action appears for the umpire (and the season's admins), which records a walkover for the team that is present using the existing walkover flow. Nothing happens automatically. |

Defaults I chose (tell me if any are wrong):
| Question | Default |
|---|---|
| Content-Security-Policy | Ship `script-src 'self' 'unsafe-inline'` (blocks every outside script, frame, object and form target without switching off the static pages and Partial Prerendering that keep the public site fast; the guard test already forbids raw HTML). Nonces are not used because they would make every page dynamic. |
| Where tokens live | Keep the tokens in the browser as now; add refresh-token reuse detection, a shorter access-token lifetime, a "where am I signed in" list, and the CSP. An HttpOnly cookie is deferred (it would rewrite web and WebSocket sign-in for a risk these already cover). |
| Onboarding | Admins bulk-import players from a CSV; each gets a one-time invite link (valid 14 days) that pre-fills name, number and team; the number counts as verified because an admin imported it. Self-registration stays, with admin verification. |
| Account deletion | A player can delete their account: name, email, phone and password are removed and sessions revoked; their matches keep a "Former player" entry so scorecards, tables and statistics stay correct. A player can also download their own data (JSON). |
| Avatars | The unused `avatar_url` field is removed (hotlinked pictures are a tracking vector and nothing shows them). |

## Architecture
- **Verification becomes a first-class state.** A number is verified by an admin (with a reason, audited, recorded as who and when) or, later, by a provider's code. The lineup rule ("verified phone") is unchanged; only the ways to get verified grow.
- **Production OTP mode.** `OTP_PROVIDER=disabled` (the production default): asking for a code answers "ask an organiser to verify your number" and nothing is generated or logged. The console provider is refused in production and never writes a code to a log. A real provider needs one new class behind the existing interface.
- **Invites are single-use secrets.** Only a hash of the token is stored; using one creates the account and joins the team in one transaction; they expire, can be revoked, and every step is audited.
- **Session families.** Every sign-in starts a family; each refresh replaces the token in the family; replaying an already-replaced token revokes the whole family and tells the person.
- **Deleting a person keeps the league intact.** Personal fields are blanked and the user is marked deleted; matches, balls and awards keep pointing at the row, which now reads "Former player" everywhere (signed-in and public).

## Data model (migration 0014)
`sessions.family_id` and `sessions.replaced_at`; `users.deleted_at`, `users.phone_verified_by`, `users.phone_verified_at`; `invites(id, token_hash unique, name, phone, team_id, season_id, created_by, created_at, expires_at, used_at, used_by, revoked_at)`; index on `audit_logs.created_at`. The toss timeout is a rule-set setting (`toss_timeout_minutes`, default 15), so it needs no table.

## Sprints (about 2 weeks)

### Sprint 19: Launch blockers (week 1)
- **Admin phone verification:** `POST /admin/users/{id}/verify-phone` (global admins; a season admin may verify members of their own season's teams) with a reason; shown as "verified by an admin"; an admin cannot verify their own number; the player is notified; the unverified message on lineups and the profile says "ask an organiser" when OTP is disabled.
- **OTP production mode** as described, and the startup guard refuses the console provider in production.
- **Onboarding:** admin CSV import with a preview (valid rows, duplicate numbers, unknown teams, numbers already registered) then create invites; invite sign-up page `/join/[token]`; a copyable and printable list of links per team; revoke and resend.
- **Toss timeout rule:** `toss_timeout_minutes` in the rule set (validated, shown on the rule versions screen); `POST /matches/{id}/toss/absent {team_id}` for the match umpire or the season's admins, allowed only after the scheduled start plus the wait while the toss is unresolved, recorded as a walkover through `declare_walkover` (so the table, chat message, notifications and reversal all already work); the toss panel shows the button only when it is allowed; the toss reminder text mentions it; `RULES.md` documents it.
- **Exit:** a whole team can be imported, invited and verified without SMS; a captain who never answers the toss ends in a walkover the table reflects; nothing logs a code in production mode.

### Sprint 20: Security and privacy (week 2)
- **Headers and policy:** Content-Security-Policy and the header set (frame-ancestors none, referrer policy, permissions policy, nosniff) from `next.config.ts`, a browser test that every screen runs under the policy with no violation (including the service worker, structured data and the install prompt) and the headers are present; **WebSocket Origin allow-list** on every socket; CORS strictly from the environment, no wildcard (startup guard); remove `avatar_url`.
- **Sessions:** refresh-token reuse detection with family revocation and a notification; a "Where you are signed in" list on the profile page with sign-out per device; a shorter access-token lifetime.
- **Privacy:** delete my account (with a password check), download my data (profile, memberships, match history, disputes I raised, notifications, push devices), "Former player" handling everywhere, short public privacy and terms pages, and a note that only essential browser storage (sign-in, season choice, install prompt) is used.
- **Retention job:** expired OTP codes, revoked and expired sessions, read notifications (exists), consumed and expired invites, and a documented retention period for audit entries.
- **Review:** OWASP Top 10 and an ASVS-style pass over every route group; per-route rate-limit budgets for chat sends, disputes, push registration, invites and public reads, each tested; input checks for control and direction-changing characters in names and messages; `pip-audit` and `pnpm audit --prod` added to CI; `docs/SECURITY.md` "accepted for now" table closed or re-justified item by item, with the items that are deployment-only moved to the checklist below.
- **Exit:** every app-level item in the old table is done or explicitly re-accepted; a stolen refresh token is detected; a player can leave and the league's numbers do not change.

## Left for you: deployment and launch checklist (not built here)
Documented in `docs/PHASE5.md` and `docs/SECURITY.md`, not implemented:
1. Production images (non-root user, no auto-reload, several API workers; web built and served without the dev server).
2. A reverse proxy with HTTPS, HSTS, request-size limit, WebSocket upgrade, and `X-Forwarded-For` overwritten (then `TRUST_PROXY=true`).
3. Strong secrets (JWT secret, database and Redis passwords), `ENVIRONMENT=production`, `OTP_PROVIDER=disabled` (or a real provider), VAPID keys if push is used, the real site address.
4. Backups of Postgres with a tested restore, monitoring and error alerts (Sentry was your choice), log shipping.
5. Real super admins (and at least two admins), retire the development admin account.
6. Check push on real phones (iPhone needs the Home Screen app) and run the whole Docker stack once.
7. A pilot round alongside WhatsApp before switching the league over.

## Edge cases to test
Verifying a number twice or one that belongs to someone else; an admin verifying their own number; a season admin verifying someone outside their season; an invite used twice, expired, revoked, or for a number that registered meanwhile; a CSV with duplicates, unknown teams, bad numbers, 1,000 rows, formula-looking names; the toss timeout when the umpire acts one minute early, when the toss was already confirmed, after a reversal, and when the match has no scheduled time; a captain who arrives just after the walkover; a replayed refresh token raced by the real owner; sign-out of one device leaving the others; deleting an account that captains a team, umpires a match, raised a dispute, holds an award or is an admin; the public site and leaderboards after a deletion; a data download with large histories; a WebSocket from a foreign origin; the CSP with the service worker, JSON-LD and install prompt; names containing right-to-left override characters.

## Risks
| Risk | Mitigation |
|---|---|
| Admins become a verification bottleneck | Bulk import and invite links verify a whole team at once; season admins can verify their own season's players; the OTP interface is ready for a provider |
| An invite link leaks | Single use, expires in 14 days, can be revoked, stores only a hash, audited |
| Deleting a player damages old results | Rows stay; only personal fields are blanked; tests check scorecards, tables, statistics and the public site afterwards |
| The CSP breaks a feature | A browser test runs every screen under it; roll out first as report-only in tests, then enforce |
| A walkover is declared too early or unfairly | Only after the scheduled start plus the wait, only by the umpire or the season's admins, fully reversible by an admin, and audited |
| Session changes lock people out | The refresh flow keeps working for normal use (tested), only a replayed token revokes, and the session list lets people sign out themselves |

## Critical files
- New: `api/alembic/versions/0014_*.py`, `api/app/routers/invites.py`, `api/app/routers/privacy.py`, `api/app/services/invites.py`, `api/app/services/privacy.py`, `api/app/services/retention.py`, `web/app/join/[token]/page.tsx`, `web/app/admin/import/page.tsx`, `web/app/privacy/page.tsx`, `web/app/terms/page.tsx`, `docs/PHASE5.md`, tests for each.
- Modified: `api/app/core/otp.py` and `core/config.py` (disabled mode, production guard), `api/app/routers/admin_users.py` (verify a number), `api/app/routers/auth.py` (session families, reuse detection, session list, shorter access token), `api/app/routers/ws.py`, `ws_me.py`, `ws_rooms.py`, `ws_public.py` (origin check), `api/app/routers/play.py` and `services/declarations.py` (toss absent), `api/app/engine/rules.py` and `rules_admin.py` (`toss_timeout_minutes`), `api/app/services/reminders.py` (toss reminder text), `api/app/worker.py` (retention), `api/app/schemas.py` and models (remove avatar, deleted users, Former player), `web/next.config.ts` (CSP and headers), `web/components/match/TossPanel.tsx`, `web/app/profile/page.tsx`, `web/app/admin/users/page.tsx`, `.github/workflows/ci.yml` (audits), `RULES.md`, `docs/SECURITY.md`, `README.md`.
- Reuse: `services/declarations.py::declare_walkover`, `routers/phone_changes.py` (approval pattern), `services/ratelimit.py::allow`, `routers/auth.py::throttle`, `services/approvals.py::ask_admins`, `routers/exports.py::cell` (CSV safety for the import and the downloads), `web/e2e/helpers.ts`.

## Verification
- API tests: verification rules (who may verify whom, self-verification refused, audit, notification, lineup rule), OTP disabled mode (nothing generated or logged) and the production guard, import preview and every failure, invite lifecycle (create, use, expire, revoke, reuse, race), toss timeout (every eligibility rule, the walkover result in the table, reversal, permissions), session families and reuse detection (including a race), session list and per-device sign-out, WebSocket origin refusal on every socket, deletion across scorecards, tables, statistics, disputes, awards and the public site, data download contents, retention job, rate-limit budgets, input character checks.
- Browser tests (phone viewport): import and invite sign-up end to end; the toss "captain absent" action appears only when allowed and produces the walkover; delete and download my data; sign out of another device; every screen under the CSP with the headers present and no violations; the install, offline and push flows still work.
- Regression: the whole existing suite (API, browser, accessibility, SEO and performance budgets) stays green; the public load test and the season load test still pass.

## Definition of done
- Players can be imported, invited and verified with no SMS; production never logs or generates a code.
- A captain who never answers the toss ends in a walkover the umpire records, and the rule is in the rulebook.
- Every app-level item in the old "accepted for now" table is done or re-justified in writing; a stolen refresh token is detected; players can delete their account or download their data without damaging the league's numbers.
- Tests, lint, browser tests and load tests are green; documented in `docs/PHASE5.md`, with the deployment checklist ready for you.
