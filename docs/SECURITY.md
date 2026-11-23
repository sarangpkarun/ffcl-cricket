# FFCL Security Review (Sprint 8)

Scope: the API, the WebSocket endpoints, the web app and the build dependencies as of the end of Phase 2.
Method: read the code for each trust boundary, wrote a failing test for every problem before fixing it, ran real
dependency audits, and used the 30-match / 240-player load test as an adversarial check. Every fixed item below has a
regression test (named in the last column) so it cannot quietly come back.

## Findings and fixes

| # | Severity | Problem | Fix | Test |
|---|---|---|---|---|
| 1 | High | `GET /users` returned every user's **email and phone number** to any signed-in player. | It now returns only `id`, `name`, `player_code`. Full details are admin-only. | `test_user_search_never_exposes_contact_details`, `test_team_and_match_views_do_not_expose_contact_details` |
| 2 | High | A tournament admin could create more tournament admins (privilege escalation path). | Only a super admin can grant or remove admin roles. Nobody can remove their own admin access, and the last super admin cannot be removed. | `test_only_a_super_admin_can_hand_out_admin_roles`, `test_revoke_rules` |
| 3 | High | No brute-force protection on login. | 10 attempts per account and 30 per address per 5 minutes, then HTTP 429 (even for the right password until the window passes). | `test_login_is_rate_limited_per_account_and_per_address` |
| 4 | Medium | OTP requests were unlimited (SMS flooding and cost) and registration was unthrottled. | 3 OTP requests per user per 10 minutes; 10 registrations per address per hour. | `test_registration_and_otp_requests_are_rate_limited` |
| 5 | Medium | Login response time revealed which emails have accounts. | A throwaway password hash is checked for unknown emails, so both paths do the same work. | `test_unknown_email_costs_the_same_work_as_a_known_one` |
| 6 | Medium | Several free-text fields and the digit list had no length cap. | Reasons are limited to 500 characters; digit input to 6 values / 40 characters. | `test_free_text_and_digit_fields_are_bounded` |
| 7 | Low | `avatar_url` accepted any scheme (`javascript:`, `data:`). | Only `http(s)` URLs at the time; the unused field was removed in Sprint 20. | (removed with the field) |
| 8 | Medium | A production server could start with the development JWT secret or with rate limits switched off. | Startup refuses (`ENVIRONMENT=production`) unless `JWT_SECRET` is strong and limits are on. | `test_production_refuses_the_development_secret` |
| 9 | High (availability) | **Found by the load test.** Every open WebSocket held a Redis connection from the same pool as ordinary commands, capped at 100. A few hundred sockets starved publishing, rate limiting and presence, and live updates silently stopped. | Subscriptions use their own pool; commands use a bounded pool that waits for a free connection instead of failing. Socket helper tasks now log why they died. | `tests/test_redis_pools.py` |
| 10 | Medium | **Found by the load test.** Two identical chat sends or reaction taps at the same instant returned HTTP 500 (the recovery path read objects SQLAlchemy had expired on rollback). | Recovery uses plain values captured beforehand. | `test_simultaneous_identical_sends_collapse_to_one_message`, `test_simultaneous_reaction_taps_never_error` |
| 11 | n/a | Dependency audit: `shadcn` (a build-time CLI) was listed as a production dependency and pulled in a moderate `minimatch` advisory. | Moved to dev dependencies. `pnpm audit --prod` and `pip-audit` now report nothing. | audits (see below) |

Fixed in earlier sprints: WebSocket tokens moved out of URLs (they were landing in access logs); password hashing moved off the
event loop; the test suite refuses to run unless `DATABASE_URL` is set explicitly.

## Checked and found sound

- **Cross-site scripting:** the web app contains no raw-HTML rendering; message bodies, names, reasons and announcements are
  rendered as text. A browser test posts `<img src=x onerror=...>` and confirms nothing runs.
- **SQL injection:** all queries are parameterised; search wildcards (`%`, `_`, `\`) are escaped.
- **Access to other people's data:** chat rooms, messages, notifications, reports and mutes are scoped on the server. A
  role-by-room test matrix covers every combination, and a second test proves the fast "which rooms can I read" lookups agree with
  the single access rule. Strangers get "not found" (HTTP 404 / socket 4403), so room ids cannot be probed.
- **Hidden digits:** the server never sends a side's digits to the other side or to spectators before the reveal, in the
  scoreboard, the chat, announcements, notifications or the live socket (tests cover each).
- **WebSocket authentication:** token in the first message, re-checked every 25 seconds, so a logged-out, suspended or removed
  user is disconnected. The token only gates the handshake.
- **CSRF / cross-site WebSocket hijacking:** authentication is a bearer header or first message, never a cookie, so a
  third-party page cannot ride a signed-in session.
- **Mass assignment:** profile updates accept only name and avatar.
- **Audit trail:** role grants and removals, suspensions, mutes, report decisions, overrides, corrections and penalties are logged
  with the actor and reason.
- **Uploads:** there are none (images and stickers were dropped), so there is no file-upload attack surface.

## Accepted risks, after the Phase 5 review

Every item that was "accepted for now" is either closed in the app, still accepted with a reason, or moved to the deployment checklist (it cannot be fixed inside the app).

| Risk | Status | Notes |
|---|---|---|
| Tokens live in `localStorage`, so a script injection would expose them. | **Reduced, re-accepted.** | A Content-Security-Policy now blocks every script, frame, plugin and form target that is not ours; nothing renders raw HTML (a test forbids it); access tokens last 10 minutes; refresh-token replay is detected and a "where you are signed in" list lets people end sign-ins. An HttpOnly cookie would mean rewriting sign-in for the web and every socket, for a risk these controls already cover. Revisit if the app ever renders user-supplied HTML. |
| `script-src` has `'unsafe-inline'`. | **Accepted.** | Next.js puts small inline scripts in each page. A per-request nonce would make every page dynamic and lose the static and partially prerendered public pages. The inline allowance matters only if an attacker can inject markup, and none can be rendered. |
| No refresh-token reuse detection. | **Closed (Sprint 20).** | Each sign-in is a family; a replayed spent token ends the whole family and notifies the person (see S9). |
| WebSockets did not check where the page came from. | **Closed (Sprint 20).** | Every socket refuses a browser page from an origin not in `CORS_ORIGINS` (see S10). |
| CORS allowed every method and header. | **Closed (Sprint 20).** | Only the needed methods and headers; production refuses a wildcard or non-https origin. |
| OTP codes written to the log. | **Closed (Sprint 19).** | See V1. |
| `avatar_url` could point anywhere (tracking). | **Closed (Sprint 20).** | The field was unused and is removed. Team `logo_url` is also an outside address; the app does not show it, and the CSP blocks outside images anyway. |
| No way to leave or take your data. | **Closed (Sprint 20).** | See S11. |
| Dependency audits run by hand. | **Closed (Sprint 20).** | `pip-audit` and `pnpm audit --prod` run in CI. |
| Rate limiting trusts the connecting address; behind a proxy that is the proxy's. | **Deployment.** | Set `TRUST_PROXY=true` only behind a proxy that overwrites `X-Forwarded-For`. |
| HTTPS, HSTS, request-body size limits. | **Deployment.** | The reverse proxy's job (checklist in docs/PHASE5.md). The app already sends the other security headers. |
| API container runs as root with auto-reload; web runs the dev server. | **Deployment.** | Production images (checklist). |
| Redis and Postgres use development credentials and no TLS. | **Deployment.** | Strong secrets, private network, least-privilege database role (checklist). |

## Addendum: Phase 3 review (Sprint 13)
Reviewed every endpoint added in Phase 3 (fixtures, results, standings, walkovers, duties, adjustments, statistics, player of the match, roster and phone changes, archive, rule versions, audit log, exports) for authorisation, input handling and data exposure.

| # | Finding | Fix or decision |
|---|---|---|
| A1 | A phone-change request could be used to find out whether a number is registered ("already taken" vs "accepted"). | Taken numbers (registered, or in someone else's open request) all return one vague message that never names the owner, and requests are limited to 5 an hour. Registration itself still tells you a number is used; that was already accepted in the Sprint 8 review. |
| A2 | The new number is only trusted after a code sent to it, but someone could register that number while the change waits for the code. | The number is checked again at approval and again at verification; if it was taken meanwhile the change fails with the same vague message and the old number stays. |
| A3 | Audit entries for phone changes could leak numbers to anyone with audit access. | Entries store masked numbers (country prefix and last two digits). The admin approvals screen shows the full new number because the admin must judge it, and nothing else does. |
| A4 | Exported CSV files open in spreadsheets, where a player or team name such as `=HYPERLINK(...)` becomes a formula. | Every text cell starting with `=`, `+`, `-`, `@`, tab or carriage return gets a leading apostrophe. Tested with hostile team names. Exports are admin-only. |
| A5 | Two admins pressing Approve at once could apply a request twice. | Requests are locked while decided (`SELECT ... FOR UPDATE`); the loser gets HTTP 409. Roster approval re-checks every condition at decision time. Tested with simultaneous approvals. |
| A6 | Audit search text containing `%` or `_` acted as a wildcard (a cheap way to match everything). | Wildcards are escaped. The viewer is admin-only, paginated by cursor (limit 200). |
| A7 | Someone could rewrite history of a closed season. | One guard (`services/archive.py`) is called by every write route that touches a season: teams, members, matches, lineups, every play and correction route, fixtures, knockouts, adjustments, duties, awards, roster changes and rule changes. A season can only be archived when every match is finished, and only unarchived by an admin (audited). The Sprint 13 test calls thirteen different write routes on an archived season and expects 409 from each. |
| A8 | A rule version could be saved with nonsense (zero overs, unknown settings) and break live scoring. | Rule changes are merged onto a copy, validated (ranges, known keys, tie-break names, over numbers within the match) and rejected with reasons. Existing versions are never edited; matches already started keep their version. |
| A9 | Admin-only data visible to others: roster requests, phone requests, audit log. | Phone requests, the audit log and exports are admin-only. Roster requests are visible to admins, the team's captain, and the two players named. Tested with outsiders. |

Accepted for now (Phase 5):
- Chat in an archived season stays open (conversation is not league data). Revisit if moderation load requires it.
- Leaderboards, history, the table and player pages are readable by every signed-in user; Phase 4 decides what becomes public.
- Statistics are computed on each request (no caching). Measured with a 33-match season: p95 under 160 ms for every read endpoint. Add a cache if seasons grow far beyond that.

## Addendum: public site (Sprint 14)
| # | Finding | Fix or decision |
|---|---|---|
| P1 | Opening data to anyone risks leaking private fields or drafts. | A separate `/public` router, never the signed-in endpoints with checks loosened; one place (`services/public.py`) decides how a person may be shown; a test scans every public response for forbidden keys, emails and phone numbers. |
| P2 | The live view could expose digits before the reveal to an anonymous viewer. | One builder serves everyone; anonymous viewers get the same rule as any spectator and more (even the umpire's "locked" view is hidden). Tested through every over state. |
| P3 | Free text written for the league (abandonment reasons, penalty reasons) could be personal. | Public views show "Match abandoned" and no penalty or declaration reasons. |
| P4 | Names of players who do not want to be listed, or who are suspended. | `show_publicly` switch (code only, no id, no page) and suspended players removed everywhere. Tested for rankings, rosters, pages, scorecards and the sitemap. |
| P5 | Anonymous traffic could overwhelm the API or sockets. | Per-address rate limit, short shared caches, live view keyed by sequence number, anonymous sockets capped per address and in total, polling fallback. |
| P6 | Server-rendered pages call the API from one address, so one limit would cover every visitor. | The web server forwards `X-Forwarded-For`; the API honours it only when `TRUST_PROXY=true`. Deployment: Nginx must overwrite that header, never pass a client-supplied one. |
| P7 | Team and player names inside structured data could close the script tag. | The only raw-markup component (`JsonLd`) escapes `<`, `>`, `&` and line separators; a test feeds it a hostile name. The guard test allows no other file. |
| P8 | Crawlers indexing signed-in pages and API JSON. | `robots.txt` disallows the signed-in routes; unknown pages are marked not indexable. |

## Addendum: installable app and push (Sprint 15)
| # | Finding | Fix or decision |
|---|---|---|
| N1 | A push subscription holds a URL our server will POST to; a hostile user could point it at internal addresses (SSRF). | https only, no credentials, port 443 only, no IP addresses, exact push-service host families (a long list of look-alike and internal hosts is tested), and the sender never follows redirects (tested against a real redirecting server). |
| N2 | A push could carry private content or lead somewhere hostile. | The payload is built only from the notification's own title, body and an in-app link; links that are not site paths become the inbox (both on the server and again in the service worker); a test builds a payload for every notification kind. Hidden digits are never in a notification, so never in a push. |
| N3 | A shared phone or computer keeps getting the previous person's alerts. | Re-subscribing the same browser moves it to the signed-in person; turning alerts off removes it on the server; dead devices are deleted automatically. |
| N4 | Push spam and cost. | Per-kind defaults with noisy kinds off, personal choices, no push while the app is in front, a limit of 10 devices per person, rate limits on registering and on the test button, and one job per notification. |
| N5 | The service worker caching the wrong thing (a stale scoreboard, or a signed-in page for the wrong person). | It stores only the offline page and an icon and never caches pages or API responses. |
| N6 | Push keys. | The private key lives in the server environment only (never committed, never sent to the browser); the public key is served from `/push/key`; the production guard refuses to start with push enabled and no keys. |

## Addendum: disputes (Sprint 16)
| # | Finding | Fix or decision |
|---|---|---|
| D1 | Disputes contain accusations and private details. | Never in the public API (scanned by a test); visible only to the raiser, the leaders of the teams involved and deciding admins; everybody else gets the same "not found" as for a dispute that does not exist, so even its existence is not revealed. |
| D2 | An admin could rule on their own team's dispute. | Admins who belong to an involved team or raised it are parties, not judges: they cannot see private notes, decide, or even see the dispute in the queue; they are not notified. Tested for a plain member, a captain and a raiser. |
| D3 | Private notes leaking to the people they are about. | Notes are filtered on the server for everyone but deciding admins, are refused from parties, and send no notifications. |
| D4 | Spam and harassment through disputes. | Only captains, vice-captains and the umpire can dispute a match (and only inside the window); conduct complaints are limited to players of that season (3 open at a time without a match); one open dispute per person per match; hourly rate limits on raising and replying; the person raising can be seen by the organisers; every step is audited. |
| D5 | Disputes used to rewrite history of a closed season. | No new disputes and no reopening in an archived season. |
| D6 | A resolution that points at an unrelated adjustment. | A linked points adjustment must exist and belong to the same season. |

## Addendum: analytics (Sprint 17)
| # | Finding | Fix or decision |
|---|---|---|
| A1 | A player's digit habits would let opponents predict their digits. | Reported only for seasons that are completed or archived, from the server for every viewer (admins and the players themselves included while the season runs); a career view counts only finished seasons; the screens explain why they are hidden. Tested signed in, public, career and per season. |
| A2 | The public cache could keep digit habits visible after a season is reopened (or hide them after it finishes). | The season's status is part of the cache key for every public analytics response; a regression test warms the cache, finishes and reopens the season and checks the figures change at once, and fails on the old key. |
| A3 | Head-to-head tables could expose players who chose not to be listed, or suspended players. | Public analytics resolve every other player through the same privacy rules as the rest of the public site: hidden players appear as their player code without an id, suspended players are left out. |
| A4 | Live analytics could show something the scorecard does not. | They read only resolved balls (the same counted balls as the scorecard); unrevealed digits do not exist as ball events, so there is nothing to leak. |

## Addendum: season admins and launch checks (Sprint 18)
| # | Finding | Fix or decision |
|---|---|---|
| S1 | A season admin could gain power over another season through a route that forgets to check the season. | `is_admin` fails closed (no season means global admins only); every season-keyed route goes through one dependency that finds the season from the id in the path; a test sends a request to every such route with another season's ids and expects 403, and another test fails if any `/admin` route has no guard at all. |
| S2 | Probing ids: a 404 for a missing thing and a 403 for another season's thing would let a season admin map other seasons. | A missing id is judged as "no season", so a season admin always gets 403; only global admins reach the 404. Unreadable chat rooms and disputes already looked the same as missing ones. |
| S3 | Granting admin power. | Only a super admin grants or revokes admin roles (a season admin cannot grant anything); a super admin cannot be limited to a season; the season must exist; every grant is audited. |
| S4 | Chat boundary for season admins. | A season admin reads and moderates only the rooms of their own seasons (season rooms by season, match rooms through the match), and is only listed as a member there. |
| S5 | Notifications reaching the wrong admins. | Roster and dispute notifications go to global admins and the admins of that season only. |
| S6 | A dropped connection ended a session (the saved sign-in was wiped on any failed request), which also made "am I signed in" hard to reason about. | Only a real 401 or 403 ends it; network and server errors keep it and retry. |
| S7 | Public load amplification: every public page prefetched the pages it links to, each costing server and API work. | Prefetching is off on the public site (transfer halved) and the public load test shows 200 viewers and 40 readers served with p95 230 ms. |
| S8 | Share previews for bots that ignore streamed metadata. | Metadata is in the head for every visitor (tested with a link-preview user agent). |

Left for launch (yours, listed in docs/PHASE5.md): a real SMS provider if wanted, backups and a restore drill, monitoring and alerting, staging and a pilot with real teams, and a second admin so a recused admin never leaves a dispute with nobody to decide it.

## Addendum: Phase 5, Sprint 19 (verification, invites, toss timeout)

| # | Risk | Control |
|---|---|---|
| V1 | One-time codes in the server log. | `OTP_PROVIDER=disabled` is the production default: asking for a code answers "ask an organiser" and creates nothing; `ConsoleOtpProvider` refuses to run in production and the startup guard refuses `OTP_PROVIDER=console` there. Tests check no code row and no log line. |
| V2 | An admin vouching for numbers is a powerful act. | Needs a written reason, is audited (`phone.verify`), records who and when on the user, notifies the person, cannot be done to yourself, and a season admin can do it only for members of their own seasons (the same refusal whether the person exists or not, so ids cannot be probed). An approved phone change takes effect at once when codes are off, with the admin recorded. |
| V3 | A leaked invite link. | A random 192-bit secret, only its hash stored; single use (row lock, tested with four simultaneous attempts); expires in 14 days; revocable; reissuing revokes the old link; the page reveals only the name, team, season and the last two digits of the number; accepting is throttled per address; every step is audited. |
| V4 | A bulk import abusing the system. | At most 500 rows and 200 KB, creation throttled per admin, teams cannot be over-filled, duplicate and already-registered numbers are refused, names with control or direction-changing characters are refused, and exports defuse formula-looking names. |
| V5 | An umpire wrongly ending a match. | The toss-absent action is allowed only after the scheduled start plus the rule's wait, only to the match umpire or season admins, only while the toss is unsettled, goes through the ordinary walkover (audited, announced) and an admin can reverse it. |

## Addendum: Phase 5, Sprint 20 (security and privacy)

| # | Risk | Control |
|---|---|---|
| S9 | A stolen refresh token used after the real owner has rotated it. | Every sign-in is a family of tokens. A refresh swaps the token (the old one is marked replaced). Replaying a replaced token more than 10 seconds later revokes the whole family, notifies the person (kind `security`) and is audited; within 10 seconds it is only refused (two tabs racing; the row is locked so exactly one wins). Logging out is a plain end, not a replay. Tested including a simultaneous race. |
| S10 | Cross-site WebSocket hijacking: another website opening our sockets with a visitor's browser. | Every socket (`/ws/me`, match, room, public) closes the handshake with 403 when an `Origin` header is present and not in `CORS_ORIGINS`. Clients that send no Origin (not browsers) are still held to the token on the private sockets. CORS allows only the needed methods and headers, and production refuses a wildcard or `http://` origin. |
| S11 | Leaving the league, and data you cannot see. | Delete my account needs the password, refuses people who must hand over a role first (admin, captain, umpire of or in the lineup of an unfinished match), blanks name, email, phone and password, ends every sign-in, removes push devices, notifications and preferences, cancels pending requests and invites, and keeps the row as "Former player" so results are unchanged (tested on the table, leaderboards, scorecards and the public site). Download my data returns everything held about the person, not other people's data, with no secrets (no password hash or tokens), and is rate limited. |
| S12 | Text that hides itself (right-to-left override, zero-width and control characters) in names, team names, chat and disputes. | One shared check rejects them (`core/text.py`); line breaks stay allowed in messages. |
| S13 | Sessions and codes piling up. | A nightly job removes expired one-time codes, expired sign-ins (kept a week past expiry so a replay is still noticed), old ended sign-ins, used or expired invites, and audit entries older than `AUDIT_RETENTION_DAYS` (default two years; 0 keeps them). |
| S14 | Content-Security-Policy and headers. | `default-src 'self'`, no outside scripts, frames (`frame-ancestors 'none'`), plugins or form targets, `connect-src` limited to our API, plus nosniff, `X-Frame-Options`, referrer and permissions policies. A browser test visits about thirty screens signed out, as a player and as an admin and fails on any violation, and proves an outside script and frame are refused. |
| S15 | Rate-limit budgets. | Checked per route group: sign-in, registration, one-time codes, phone changes, push registration and test, disputes and their messages, chat sends, reactions and reports, invite creation, preview, lookup and acceptance, data download, account deletion and public reads each have a limit and a test. |

Retention periods: one-time codes a day after expiry; sign-ins a week after expiry; invites 90 days after use or expiry; read notifications 90 days; audit entries two years; match records for as long as the league keeps the season.

## Re-running the checks

```
make test                                         # API + web unit tests (includes tests/test_security.py)
cd web && pnpm audit --prod                       # web dependencies
cd api && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt \
  && uvx pip-audit -r /tmp/req.txt --no-deps --disable-pip      # Python dependencies
cd api && uv run python -m loadtest.chat_load --matches 30      # concurrency, fan-out and pool limits
cd api && uv run python -m loadtest.season --teams 6            # a whole season: play, rebuild, reconcile, archive
cd api && uv run python -m loadtest.public_load --viewers 200 --push 500   # anonymous viewers, public pages and push fan-out
```

## Deployment checklist (before real users)

1. `ENVIRONMENT=production`, a random `JWT_SECRET` (32+ characters), `AUTH_RATE_LIMITS_ENABLED=true`.
2. Behind Nginx with TLS; `TRUST_PROXY=true`; body size limit; security headers.
3. Several API workers (the 4-worker load test passes: Redis fans live updates out across workers).
4. A worker container running `arq app.worker.WorkerSettings` for reminders.
5. Real SMS provider; change every default password; rotate the development admin account.
