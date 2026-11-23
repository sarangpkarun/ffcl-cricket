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
| 7 | Low | `avatar_url` accepted any scheme (`javascript:`, `data:`). | Only `http(s)` URLs. | `test_avatar_must_be_a_web_url` |
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

## Accepted for now, to finish in Phase 5 (launch hardening)

| Risk | Why it is acceptable now | Plan |
|---|---|---|
| Access and refresh tokens live in `localStorage`, so a script injection would expose them. | No injection path was found (see XSS above) and nothing renders raw HTML. | Add a strict Content-Security-Policy; consider moving the refresh token to an HttpOnly cookie. |
| No refresh-token reuse detection (a stolen, already-rotated token is simply refused). | Rotation already invalidates the old token. | Revoke the whole session family when a rotated token is replayed. |
| Rate limiting trusts the connecting address. Behind a proxy that is the proxy's address. | Single-host development. | Set `TRUST_PROXY=true` only behind Nginx that overwrites `X-Forwarded-For`. |
| HTTPS, HSTS, security headers, request-body size limits. | Handled by the reverse proxy, which is Phase 5. | Nginx config with TLS, `client_max_body_size`, security headers. |
| API container runs as root with auto-reload. | Development image. | Separate production image: non-root user, no `--reload`, several workers. |
| Redis and Postgres use development credentials and no TLS. | Local only. | Strong secrets, network isolation, TLS, least-privilege database role. |
| OTP codes are written to the log (console provider). | No SMS provider is configured yet. | Plug in a real SMS provider; never log codes. |
| Dependency audits are run by hand. | Both are clean today. | Add `pnpm audit --prod` and `pip-audit` to CI. |

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

## Re-running the checks

```
make test                                         # API + web unit tests (includes tests/test_security.py)
cd web && pnpm audit --prod                       # web dependencies
cd api && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt \
  && uvx pip-audit -r /tmp/req.txt --no-deps --disable-pip      # Python dependencies
cd api && uv run python -m loadtest.chat_load --matches 30      # concurrency, fan-out and pool limits
cd api && uv run python -m loadtest.season --teams 6            # a whole season: play, rebuild, reconcile, archive
```

## Deployment checklist (before real users)

1. `ENVIRONMENT=production`, a random `JWT_SECRET` (32+ characters), `AUTH_RATE_LIMITS_ENABLED=true`.
2. Behind Nginx with TLS; `TRUST_PROXY=true`; body size limit; security headers.
3. Several API workers (the 4-worker load test passes: Redis fans live updates out across workers).
4. A worker container running `arq app.worker.WorkerSettings` for reminders.
5. Real SMS provider; change every default password; rotate the development admin account.
