# FFCL Phase 4: Public site and polish

Plan for Phase 4 (roadmap weeks 18-22). Sprints 14 to 18 follow the Phase 3 sprints.


## Context
Phases 1 to 3 made the league run inside the app: matches, chat, fixtures, table, statistics, approvals, archive. But everything sits behind a login, so the people who care most (family, friends, the WhatsApp group) cannot follow a match or check the table without an account, nothing reaches a phone that is not looking at the app, and the organisers have no way to handle a complaint except chat. Phase 4 opens the league up and makes it comfortable: **anyone can follow the league without signing in, players get alerts on their phone, disputes are handled in one place, and several seasons can run side by side.**

What already exists and is reused: the derived table and statistics (`services/results.py::season_table`, `services/stats.py::load/totals_for`, `engine/leaderboards.py`), the live scorecard builder in `routers/live.py`, `routers/standings.py::bracket`, `routers/seasons_admin.py::history`, the notification pipeline (`services/notify.py::notify`, `services/outbox.py::flush`, `ws_me.py`, per-kind preferences), the arq worker (`worker.py`, `services/reminders.py`), the archive guard (`services/archive.py`), rate limiting (`services/ratelimit.py::allow`), audit logging, and the e2e and load-test helpers (`web/e2e/helpers.ts`, `api/tests/helpers.py`, `api/loadtest/season.py`).

## Decisions
Answered by you:
| Question | Decision |
|---|---|
| What can a signed-out visitor see? | **Read-only league data with players by name:** home, seasons, fixtures, live scorecards, table, results, leaderboards, history, rules, team and player pages. Never email, phone, chat, drafts or hidden digits. |
| Multi-tournament | **Several seasons side by side.** Seasons already own their teams, matches and rules. Add season slugs, a public season list and switcher, and **season-scoped admins** so two seasons can run at once. No new top-level entity. |
| Notification channels | **Browser push (Web Push, free, own VAPID keys) with an installable app.** Email and WhatsApp are not built; push goes through a small delivery interface so they can be added later. |
| Scorecard exports and highlights | **Skipped for Phase 4.** Disputes and analytics are in. |

Defaults I chose (tell me if any are wrong):
| Question | Default |
|---|---|
| Player privacy | A player can switch off "show my name on the public site" in their profile; they then appear as their player code only. Suspended or banned players are never shown. |
| Digit analytics | Individual digit habits (which digits a player tends to pick) are shown only **after the season is completed or archived**, never during it, because they would help opponents predict digits. |
| Who can raise a dispute | A captain, vice-captain or the match umpire, for a match, within 48 hours of the result (setting in the rule set). Any player can file a conduct complaint at any time. Admins on the disputed team cannot decide it. |
| Disputes and public | Never public. Visible to the person who raised it, the captains of the teams involved, and admins. |
| Push noise | Push is on by default only for the important kinds (your over, toss, result, fixtures, adjustments, approvals, disputes); wicket and over-complete stay off. A user who currently has the app open (live socket) is not pushed as well. |
| Public caching | Responses are cached for 5 to 30 seconds. Live match pages poll or use a read-only socket; the public never sees anything a spectator signed in could not see. |
| Offline | The installed app shows a friendly offline page; live data is never cached, so nothing stale is shown as current. |

## Architecture
- **A separate read-only public API** (`/public/*`), never the authenticated endpoints with the checks loosened. It calls the same service functions, so numbers cannot differ, and returns only public fields. Everything is allow-listed in one serializer module (`services/public.py`); a test walks every response and fails if a field named email, phone, password, token, digits (before reveal) or chat appears.
- **Anonymous viewers** are `None` where the live builder previously required a `User`. `routers/live.py::live` is refactored into `services/live_view.build_live(db, match, viewer)`, shared by the signed-in and public endpoints, so hidden digits stay hidden by the same code path.
- **Public pages are server-rendered** (Next 16 server components with `use cache` and a short `cacheLife`) in a `(public)` route group with its own layout (no login prompt, no bottom nav), so they are indexable, fast and shareable. Presentational pieces (table, leaderboard card, scorecard, player stats) are extracted from the existing signed-in pages into `components/league/*` and used by both.
- **Abuse protection:** per-IP rate limits (Redis `allow`), `Cache-Control` headers, a 30-second Redis cache for the heavy reads (stats, history, analytics), a cap on anonymous sockets per IP, and `robots.txt` that keeps crawlers off `/public` JSON.
- **Push** is delivered by the worker, not the request: `outbox.flush` enqueues an arq job per notification, the worker sends with `pywebpush`, dead subscriptions (404 or 410) are deleted. Subscription endpoints are validated against known push-service hosts (SSRF guard).
- **Season scoping:** `is_admin(db, user, season_id=None)`. A `tournament_admin` role row with a `season_id` is admin only for that season; a row without one is global. Every season-scoped route passes its season (directly, or via the match or team). A test enumerates every route that depends on `require_admin` and proves a scoped admin gets 403 on another season.
- **Analytics are derived on demand** from the same counted balls the scorecard uses (extend `stats.load` to keep per-innings counted balls with over types), cached 30 seconds for the public.

## Data model (migrations 0011-0013)
- 0011: `seasons.slug` (unique, backfilled from the name), `seasons.is_public` (default true for active, completed, archived; false for draft), `seasons.cloned_from_id`; `users.show_publicly` (default true).
- 0012: `push_subscriptions(id, user_id, endpoint unique, p256dh, auth, user_agent, created_at, last_success_at, failures)`; `notification_prefs.push` (nullable: empty means the kind's default).
- 0013: `disputes(id, season_id, match_id null, kind scoring|conduct|eligibility|umpiring|other, against_team_id null, raised_by, body, status open|in_review|resolved|dismissed, outcome, resolved_by, created_at, resolved_at)` and `dispute_messages(id, dispute_id, author_id, body, internal bool, created_at)`; a dispute may point at the adjustment or reversal that resolved it (`resolution_ref` JSON).

## Sprints (about 5 weeks)

### Sprint 14: Public API and public site (weeks 1 and 2) ✅ done
- Migration 0011. Season slugs and `is_public`; admin toggle; slug shown in admin season setup.
- `services/live_view.py` extracted from `routers/live.py`; `routers/public.py` with: `/public/seasons`, `/public/seasons/{slug}` (overview), `/fixtures`, `/results`, `/standings`, `/bracket`, `/leaderboards`, `/teams/{id}`, `/players/{id}`, `/history`, `/rules` (plain-language rule summary built from the effective config), `/public/matches/{id}/live`. Drafts, unpublished seasons and hidden players excluded. IP rate limit, cache headers, Redis cache for heavy reads.
- Anonymous live updates: read-only socket `/ws/public/matches/{id}` that carries only sequence numbers (clients refetch), capped per IP, with 10-second polling as the fallback.
- Player privacy switch in the profile.
- Next: `(public)` route group and layout; pages `/` (public home for signed-out visitors; signed-in users still get their dashboard), `/league`, `/league/[slug]` (overview: live now, next fixtures, latest results, table snapshot, leaders), fixtures, results, table, bracket, leaderboards, teams, players, matches (scorecard with live updates), history, rules. A "Sign in" prompt where an action needs an account.
- SEO and sharing: page metadata, `sitemap.ts` (seasons, teams, players, matches), `robots.ts`, `opengraph-image` for matches and teams, JSON-LD `SportsEvent` on matches.
- **Exit:** a signed-out browser follows a live match, sees the table update, browses a past season; the page source already contains the content; a hidden player and a draft fixture appear nowhere.

### Sprint 15: Installable app and browser push (week 3) ✅ done
- `app/manifest.ts`, icons (generated with the icon file conventions), theme colour, install prompt component (Chrome's prompt, plus short iOS "Add to Home Screen" instructions), offline page.
- `public/sw.js`: handles `push` (shows title, body and link) and `notificationclick` (focus or open the link). No API caching.
- Migration 0012. `POST/DELETE /me/push/subscriptions`, `GET /push/key`; endpoint host allow-list, https only, at most 10 per user. Notification settings page gets a Push toggle per kind plus "Enable on this device".
- `services/delivery.py` (channel interface, push channel), worker job `send_push`, retry with backoff, deletion of dead endpoints, skip when the user has a live socket, VAPID keys from environment (the production guard refuses to start without them when push is enabled).
- **Exit:** a device subscribes, an over assignment produces a push that opens the right match, an unsubscribed or expired device is cleaned up, and nothing hidden is in any payload.

### Sprint 16: Disputes and complaints (week 4)
- Migration 0013. Raise (captain, vice-captain, umpire, within the window; any player for conduct complaints), thread of messages, admin-only internal notes, status flow, outcome text, link to the action taken (result reversal, ball correction, points adjustment) with one-click shortcuts to the existing screens.
- Notifications to the raiser, the other team's captain and admins; a worker job reminds admins about disputes open more than 72 hours.
- Screens: raise from a finished match page, "My disputes", admin **Disputes** queue (filters, assign to me, resolve or dismiss), dispute count badge on the admin home.
- Rules: no new disputes in an archived season; an admin who belongs to a disputed team cannot resolve it; everything audited.
- **Exit:** a captain disputes a result, an admin investigates with internal notes, reverses the result through the existing tool and resolves the dispute, and both captains are told.

### Sprint 17: Advanced analytics (week 4 to 5)
- `services/analytics.py` (pure functions in `engine/analytics.py`): match (worm of runs per ball for both innings, runs per over, wickets timeline, powerplay overs), team (powerplay versus normal-over run rate, batting first versus chasing record, toss decision and win rate, average and highest score), player (form over the last matches, batter versus bowler head-to-head, runs and wickets by over type), season (toss versus result, chase success, average first-innings score), and digit habits for completed seasons only.
- Lightweight SVG chart components (worm, bars, trend); no chart library. Match analytics tab, team and player analytics sections, a Season insights page. Public versions read the same data (digit habits only for completed seasons).
- **Exit:** every analytics total reconciles with the scorecard and ledger (a test sums the over-by-over runs to the innings total), and digit habits are absent while a season is active.

### Sprint 18: Multiple seasons, polish and launch checks (week 5)
- `is_admin` with a season argument and scoped admin roles; admin People screen can grant a season-scoped admin; the route-matrix test.
- Season switcher in the app (remember the last season), "start a new season from a previous one" (copies the rule version and optionally the teams without matches), admin dashboard per season.
- Accessibility pass (axe checks in Playwright on every public page and the main signed-in pages, keyboard use, colour contrast, focus order, reduced motion), performance pass (bundle sizes, image and font loading, `cacheLife` tuning, Lighthouse run on key pages), SEO check.
- Load test for the public side (200 anonymous viewers on a live match plus page loads) and the notification fan-out to push; security addendum; docs.
- **Exit:** Phase 4 definition of done below.

## Edge cases to test
A signed-out request for a draft fixture, a draft season, a hidden or suspended player, a private chat room, a dispute; a live match during the submission window (no digits yet) and after the reveal; an anonymous socket flood from one address; a match corrected while public viewers are connected; a season switched from public to hidden while viewers are on it; slug collisions and renames; a push endpoint that is not on the allow-list or points at a private address; a subscription that returns 410; the same device subscribing twice; a user with the app open receiving a notification (no duplicate push); push payloads for every notification kind (no digits, no private data); dispute raised after the window, twice for the same match, or by the wrong person; an admin who plays for the disputed team; resolving a dispute whose result is later changed; a scoped admin using a match id, team id or roster-change id from another season; two seasons running at once with chat, fixtures and the table staying separate; analytics for a match with a walkover or abandonment (no balls); digit habits requested for an active season.

## Risks
| Risk | Mitigation |
|---|---|
| Public data leaks something private (email, hidden digits, drafts) | Separate `/public` router with allow-listed serializers; one shared live builder; a test that scans every public response for forbidden fields; the signed-out e2e checks |
| Anonymous traffic overwhelms the API or sockets | IP rate limits, short caches, Redis cache for heavy reads, capped sockets per IP, public load test with 200 viewers |
| Push endpoints used to make the server call arbitrary URLs (SSRF) | https only, host allow-list for known push services, no redirects followed, subscription cap |
| Push spam or leaking content | Per-kind defaults, user preferences, payloads built from existing notification text only, skip when the user is live in the app |
| Analytics help opponents predict digits | Digit habits only for finished seasons; everything else is aggregate or after the match |
| Scoped admins miss a route and gain power over another season | `is_admin` takes the season; a test enumerates every admin-protected route and proves cross-season 403 |
| Disputes become a place for abuse | Window, one open dispute per match and raiser, recusal rule, internal notes, audit log, admin reminders |
| SEO and caching show stale live data | Live pages are client-updated; cache lifetimes of seconds; never cache the live JSON for more than 5 seconds |
| Service worker caches the wrong thing | The worker never caches API or HTML; only the offline page and icons |

## Critical files
- New (API): `services/public.py`, `services/live_view.py`, `services/delivery.py`, `services/push.py`, `services/disputes.py`, `services/analytics.py`, `engine/analytics.py`; routers `public.py`, `ws_public.py`, `push.py`, `disputes.py`, `analytics.py`; migrations 0011-0013; `loadtest/public_load.py`.
- Modified (API): `db/models.py`, `routers/live.py` (uses `build_live`), `routers/seasons.py` and `seasons_admin.py` (slug, public flag, clone), `routers/users.py` and `routers/auth.py` (privacy switch), `routers/notifications.py` (push prefs), `services/outbox.py` and `services/notify.py` (enqueue push), `worker.py`, `deps.py` (`is_admin` with season), `engine/rules.py` (`dispute_window_hours`), `core/config.py` (VAPID settings, production guard), and the roughly 60 admin-protected routes (mechanical change: pass the season to the admin check).
- New (web): `app/(public)/layout.tsx` and pages under `app/(public)/league/...`, `app/manifest.ts`, `app/sitemap.ts`, `app/robots.ts`, opengraph images, `public/sw.js`, `components/league/*` (extracted), `components/charts/*`, `components/InstallPrompt.tsx`, `app/disputes/*`, `app/admin/disputes/*`, `app/insights/*`, `lib/push.ts`.
- Modified (web): signed-in pages that now use the shared `components/league/*`, `app/page.tsx` (public home when signed out), `app/profile/page.tsx` (privacy switch), `app/notifications/page.tsx` (push settings), `components/TopBar.tsx`, `lib/api.ts`.
- Reuse: `services/ratelimit.py::allow`, `services/results.py::season_table`, `services/stats.py`, `engine/leaderboards.py`, `routers/standings.py::bracket`, `services/archive.py::ensure_open`, `services/approvals.py::ask_admins`, `routers/adjustments.py` and `declarations.py` (dispute outcomes link to them), `web/e2e/helpers.ts`, `api/tests/helpers.py`, `loadtest/season.py`.

## Verification
- API tests: every public endpoint with a signed-out client (content, filters, drafts and hidden players absent, caching headers, rate limit); a response scanner for forbidden fields; live view before and after reveal; public socket cap; push subscription validation and delivery with a fake sender (preferences, dedupe against live socket, dead endpoint cleanup); dispute lifecycle, window, recusal, visibility; analytics reconciliation and the digit-habit rule; scoped admin route matrix; slug rules and season clone.
- Engine tests: analytics functions with worked examples and property tests (over-by-over runs sum to the innings total).
- Browser tests (phone viewport, signed-out context): follow a live match and watch the table change, browse a past season, page source contains the content, sitemap and robots and manifest respond, install prompt appears, a push is delivered to the service worker (Chromium's push test hook) and opens the match, a captain files a dispute and an admin resolves it, axe checks have no serious violations.
- Load test: 200 anonymous viewers on a live match plus public page traffic while matches are played; push fan-out to 500 fake subscriptions; zero errors and p95 under a second.
- Manual: install the app on a real phone, subscribe, receive a push for a real over assignment.

## Definition of done
- A signed-out visitor can follow the league (live match, table, fixtures, results, stats, history, rules) with fast, indexable pages, and nothing private is exposed.
- Players can install the app and receive browser push for the kinds they choose; dead devices are cleaned up.
- Disputes and complaints are raised, discussed, resolved and audited in the app.
- Analytics reconcile with scorecards and never reveal digit habits during a live season.
- Two seasons run side by side with season-scoped admins, and a scoped admin cannot touch another season.
- Accessibility, performance and SEO checks pass; tests, lint, browser tests and the load tests are green; documented in `docs/PHASE4.md`.

## Sprint 14 outcome
Built:
- **Public API** (`/public/*`, `routers/public.py`): seasons list and overview, fixtures, standings, bracket, leaderboards, rules in plain language, history, team and player pages, match with live view, and a sitemap feed. It calls the same service functions as the signed-in API, so numbers cannot differ (a test compares the two), and then removes everything private. No login is needed; a signed-in user can call it too.
- **One live builder** (`services/live_view.py::build_live`) now serves both the signed-in `/matches/{id}/live` and the public one. An anonymous viewer gets no "your" data, no unrevealed digits (even while the umpire sees them locked), names as the public may see them, no free-text reasons and no umpire id.
- **Privacy** (`services/public.py`): a player can switch off "show my name on the public site" on the profile page; they then appear as their player code with no id and no page. Suspended or banned players are removed from rankings, rosters and pages. Draft matches, hidden seasons, chat, emails and phones never appear; a test scans every public response for forbidden keys, emails and phone numbers. The free-text reason of an abandoned match is replaced by "Match abandoned" publicly.
- **Season slugs and visibility** (migration 0011): every season has a readable address (`/league/ffcl-season-24`) that never changes when the season is renamed (admins can edit it; reserved words and clashes are refused). Seasons start public unless they are drafts, a draft that goes live becomes public, and admins can hide a season with a checkbox on the season setup page.
- **Abuse protection**: per-address rate limit (default 300 a minute, setting `public_rate_limit_per_minute`), `Cache-Control` headers, a shared 10 to 60 second Redis cache for the heavier reads, and the live view cached by the match's sequence number so a change shows at once while a crowd shares one build. The anonymous live socket (`/ws/public/matches/{id}`) carries only "changed, seq N", is capped at 5 per address and 3,000 in total (Redis counters, released on close), refuses drafts and hidden seasons, and the page falls back to polling every 8 seconds if the socket is unavailable.
- **Public site** (Next.js server components that stream fresh data at request time, so search engines receive the full page): landing page at `/` for signed-out visitors (signed-in users still get their dashboard), `/league` (seasons), `/league/[slug]` (overview: live now, next matches, latest results, table snapshot, leaders), fixtures, results, table with knockouts, stats, rules, team, player and match pages, and `/league/history`. A match page updates itself live. Visitors see times in their own time zone.
- **Shared components** extracted from the signed-in pages and used by both sites: points table, leaderboards, player figures and match history, knockout cards.
- **SEO and sharing**: titles and descriptions per page, canonical links, `sitemap.xml` (seasons, teams, matches, visible players), `robots.txt`, share images for the site and for each match (teams, score, result), JSON-LD `SportsEvent` on match pages.
- Migration 0011 (`seasons.slug`, `is_public`, `cloned_from_id`; `users.show_publicly`). Existing seasons were given slugs and made public unless they were drafts.

Tests: 17 public API tests (visibility, slugs, parity with the signed-in numbers, privacy, no private data anywhere, digits hidden until the reveal, abandoned reason, drafts, sitemap, rate limit and cache headers, cache behaviour, history, the anonymous socket and its limits), 2 plain-language rules tests, 1 JSON-LD escaping test, and a browser test (signed-out: page source holds the content, table, privacy, a live match that updates by itself while digits stay hidden, sitemap and robots, a signed-in user still gets the dashboard, an admin hides the season).

Things the tests found:
- The browser's own 2-second HTTP cache served the live JSON after a change event, so a page could sit on stale data. The page's own refresh now bypasses the browser cache.
- The security guard that forbids raw HTML also blocked JSON-LD. It now allows exactly one file, `components/JsonLd.tsx`, which escapes everything that could break out of the script tag, and a test proves hostile names cannot.

Decisions and limits:
- Player pages on the public site are per season (a player's other public seasons are linked); there is no combined career page yet.
- Server-rendered pages forward the visitor's address (`X-Forwarded-For`) so the rate limit applies per visitor, not per web server. In production run behind Nginx that sets this header and set `TRUST_PROXY=true`.
- In Docker the web service reaches the API at `API_INTERNAL_URL=http://api:8000`; `NEXT_PUBLIC_SITE_URL` sets the public address used in the sitemap and share cards.
- Unknown seasons or matches show a "not found" page, but because pages stream, the HTTP status is 200; the page is marked not indexable.

## Sprint 15 outcome
Built:
- **Installable app**: web app manifest (name, icons with a maskable one, theme colour, shortcuts to Fixtures, Points table and Notifications), icons drawn by the server so there are no image files to maintain, and an **install banner**: Chrome and Edge show it when the browser says the app can be installed, iPhone Safari gets a short "Share, then Add to Home Screen" hint, and "Not now" is remembered.
- **Service worker** (`public/sw.js`): shows push notifications, opens the right page when one is tapped (reusing an open window; only paths inside the site are ever opened), and shows a friendly **offline page** when a page cannot load. It never stores API responses or pages, so nothing stale can be shown as current. Its push and tap logic has its own unit tests (odd or hostile payloads included).
- **Browser push** (Web Push with our own VAPID keys, `python -m app.make_vapid` makes them):
  - Devices: `GET /push/key`, `POST /me/push/subscriptions` (also called when the same browser re-subscribes; a device used by someone else moves to whoever is signed in), list, remove by id or by address, and `POST /me/push/test` ("send a test alert", with the result). Limit of 10 devices per person.
  - **Delivery** is a background job (`send_push`) queued when a notification commits, through a small channel interface (`services/delivery.py`) so email or WhatsApp could be added later. Pushes go only to people who want them, are skipped while the person has the app open and in front, and dead devices (404 or 410 from the push service, or five failures in a row) are deleted; a nightly job forgets devices that never worked. One crashing device never blocks the others.
  - **Who gets what**: pushes are on by default for the important kinds and off for wicket, over complete, mention and reply; each person can change every kind (`notification_prefs.push`, shown as "Alerts on this device" on the Notifications page next to the existing in-app choices).
  - **Foreground rule**: the page tells the server every 20 seconds while it is visible (and when it is hidden); the server remembers for 45 seconds. A person reading the app gets the in-app toast, not a second alert on their phone.
  - **Safety**: an endpoint must be a plain https address of a known push service (Google, Mozilla, Apple, Windows; no IP addresses, no credentials, no other ports, no look-alike hosts), the sender never follows redirects, and a payload is only title, body and an in-app link (an external link becomes the inbox). The production guard refuses to start with push enabled but no keys.
  - `PUSH_DRY_RUN=true` logs what would be sent instead of sending it (staging and browser tests).
- Migration 0012 (`push_subscriptions`, `notification_prefs.push`).

Tests: 56 push API tests (endpoint safety table with look-alike and internal hosts, key checks, links, a payload check for every notification kind, device registration limits and ownership, defaults and overrides, foreground rule, gone and flaky devices, crash isolation, the test button, purge, redirect refusal against a real local server, VAPID key validity, the production guard, the socket heartbeat, and an end-to-end league event becoming a push), 3 service worker unit tests, and 2 browser tests (manifest, icons, offline page, install banner for Chrome and iPhone; then a real subscribe flow with a fake push service, preference toggles, the test alert, no push while the app is in front, a push once it is hidden, the service worker showing a delivered push through the browser's own test hook, and turning it off).

Decisions and limits:
- A real push to a real phone cannot be proven by an automated test. The browser tests prove everything on our side (what is sent, to whom, when, and how the worker shows it); the manual check in the verification list (install on a phone, subscribe, receive an alert) is still to do before launch.
- iPhone only delivers push to apps added to the Home Screen (iOS 16.4 or later); the settings page says so.
- The Docker `worker` container needs the same push settings as the API (they come from `.env`).
- Push is off unless `PUSH_ENABLED=true` and the keys are set; with it off the app behaves exactly as before.
