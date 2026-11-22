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

## Re-running the checks

```
make test                                         # API + web unit tests (includes tests/test_security.py)
cd web && pnpm audit --prod                       # web dependencies
cd api && uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/req.txt \
  && uvx pip-audit -r /tmp/req.txt --no-deps --disable-pip      # Python dependencies
cd api && uv run python -m loadtest.chat_load --matches 30      # concurrency, fan-out and pool limits
```

## Deployment checklist (before real users)

1. `ENVIRONMENT=production`, a random `JWT_SECRET` (32+ characters), `AUTH_RATE_LIMITS_ENABLED=true`.
2. Behind Nginx with TLS; `TRUST_PROXY=true`; body size limit; security headers.
3. Several API workers (the 4-worker load test passes: Redis fans live updates out across workers).
4. A worker container running `arq app.worker.WorkerSettings` for reminders.
5. Real SMS provider; change every default password; rotate the development admin account.
