# FFCL Phase 2: Real-time Communication (plan)

**Deliverable on approval:** write this document to `/home/sarang/Documents/FFCL/docs/PHASE2.md` (the only file created before implementation starts).

## Context
Phase 1 made a match playable in the app. The league still talks on WhatsApp, so players leave the app mid-match. Phase 2 moves that conversation in: a season-wide chat room, a chat per match, a private umpire channel, automatic match announcements, and in-app notifications. Exit goal (from the roadmap): **a match runs entirely in-app, replacing the WhatsApp group.**

Phase 1 pieces we build on: WebSocket + Redis pub/sub (`api/app/realtime.py`, `api/app/routers/ws.py` with first-message auth), `commit_match()` in `api/app/routers/play.py` (the single place match state is committed and announced), role checks (`ensure_official`, `can_manage`, `is_admin`), the test helpers (`api/tests/helpers.py`, `conftest.py::make_user`), the browser test, and the load simulator.

## Decisions (defaults; each is a setting, change on request)
| Question | Default |
|---|---|
| Who may read/post in the season room | Participants only: approved team members of that season, umpires, admins. Spectators later (Phase 4). |
| Match room access | Lineup players of both teams, both captains, the umpire, admins. Kept readable after the match. |
| Umpire channel | Umpire + admins only. |
| Chat while an over is open | The over's batter and bowler cannot post in the match room while submissions are open (stops digit leaks and collusion). Everyone else can. |
| Digits in system messages | Never before the reveal. Messages are generated after an over resolves. |
| System message volume | One line per wicket, one per six, one summary per over (includes fours). |
| Edit / delete | Edit own message within 15 min (shows "edited"). Delete own any time. Admins/umpires can delete anything (soft delete, "message removed"). |
| Mentions | Picked from a member list (`@name`), sent as explicit user ids. Names are not unique, so no text parsing. |
| Images and stickers | **Dropped** (owner decision during Sprint 6). Chat is text, reactions and mentions only. |
| Notifications | In-app now. Browser push and email are Phase 4. |
| Pulled forward from Phase 3 | Admin user-management screen (grant roles, suspend). Phone-change approval stays in Phase 3. |
| Needs your rulebook answer | Toss timeout default when a captain is absent (never built). |

## Architecture
- **PostgreSQL is the source of truth** for messages and notifications. Redis only fans out and rate-limits.
- **Send over REST, receive over WebSocket.** `POST /rooms/{id}/messages` carries a client-generated `client_id` (unique per sender and room) so retries never duplicate. The server then publishes to Redis channel `room:{id}`; the room socket pushes it to members.
- **Room socket** `/ws/rooms/{room_id}`: same first-message token auth as the match socket, then a membership check (close 4403 if not a member). Server events: `message`, `edited`, `deleted`, `reaction`, `pinned`, `typing`, `presence`. Client events: `typing`, `read`. Chat payloads can carry the message body because every subscriber is already authorised for that room.
- **User socket** `/ws/me`: pushes new notifications (`user:{id}` channel).
- **System messages are written in the same transaction as the state change** (toss confirmed, over resolved, penalty, result) and published after commit. Extend `commit_match()` with an outbox list on the session so a message exists if and only if the state change committed.
- **Ordering and history:** messages ordered by a bigint id; history is cursor-paginated (`before=<id>`). Reconnect refetches everything after the last seen id.
- **Presence and typing:** Redis keys with TTL (heartbeat every 20 s); typing events throttled to one per 2 s per user.
- **Safety:** per-user rate limit (10 messages / 10 s / room, Redis token bucket), body ≤ 2000 chars, plain text only (React escapes; no HTML/markdown rendering), no file uploads.

## Data model (0003 rooms + messages, shipped in Sprint 5; Sprint 6 adds reactions, reads, reports, mutes, reply/pin/image columns; Sprint 7 adds notifications)
- `chat_rooms(id, kind season|match|umpire, season_id, match_id, scope_key unique)`: created automatically with the season, and with each match (match + umpire rooms).
- `chat_messages(id bigserial, room_id, sender_id null for system, kind user|system|announcement|sticker, body, meta jsonb, reply_to_id, image_url, client_id, created_at, edited_at, deleted_at, deleted_by, pinned_at, pinned_by)`; unique `(room_id, sender_id, client_id)`; GIN full-text index on `body` for search.
- `message_reactions(message_id, user_id, emoji)` unique triple.
- `chat_reads(room_id, user_id, last_read_id)`: read receipts as a per-room cursor (cheap; shows "seen by N").
- `message_reports(id, message_id, reporter_id, reason, status open|actioned|dismissed, resolved_by)`.
- `chat_mutes(user_id, season_id, until, reason, by)`.
- `notifications(id, user_id, kind, title, body, data jsonb, dedupe_key, created_at, read_at)` unique `(user_id, kind, dedupe_key)`.
- `notification_prefs(user_id, kind, in_app bool)`.

## Sprints (about 4 weeks)

### Sprint 5: Chat foundation (week 1) ✅ done
- Migration 0003; auto-create rooms (hook season creation in `routers/seasons.py`, match creation in `routers/matches.py`); backfill existing seasons/matches.
- `services/chat.py`: one `can_read(room, user)` / `can_post(room, user)` function used by every endpoint and socket (single place for the access matrix).
- REST: send, list (cursor), edit (15-min window), soft delete.
- Room socket + presence list; rate limiter; reconnect resync.
- UI: **Chat** tab in the bottom nav (season room), **Score | Chat** tabs on the match page, message list with load-older, composer fixed above the nav (mobile safe-area).
- **Exit:** two players chat live in the season room and the match room; non-members are refused on REST and socket.

### Sprint 6: Rich chat and moderation (week 2) ✅ done
- Replies/quotes, reactions (small emoji set, toggle), @mentions (picker, notifies mentioned users), pinned messages, admin announcements (pinned banner), typing indicator, read receipts, message search (Postgres full-text, scoped to rooms the user can read).
- Reports: any member reports a message; admin queue.
- Moderation: admin/umpire delete, mute a user (time-limited) per season; mute blocks posting but not reading.
- UI: `/admin/moderation` (reports, mutes, announcement composer).
- **Exit:** every chat feature in the roadmap works on a phone; a reported message can be removed and its author muted.

### Sprint 7: System messages, umpire channel, notifications (week 3)
- `post_system()` hooks in `routers/play.py` (same transaction, published after commit): toss result and choice, innings start, wicket and six lines, over summary with running score, penalty (and void), innings break with target, result. Umpire-room entries for overrides, corrections, penalty voids.
- Chat lock for the active batter and bowler while an over's submissions are open (server-enforced, shown in the composer).
- Notifications API (`GET /notifications`, mark read, read all, unread count), bell with badge, `/notifications` page, `/ws/me`, per-kind preferences. Triggers: umpire assigned, toss ready (captains), your over has started ("submit digits now"), penalty, wicket on your team, over complete, result, announcement, mention, reply.
- **Exit:** a full match produces a correct, readable announcement feed, and players get a notification when it is their turn to submit.

### Sprint 8: Scheduling, admin users, hardening (week 4)
- ARQ worker (`worker` service in compose, `api/app/worker.py`): match reminders (1 hour, 10 minutes), toss reminder, 30-second submission-deadline alert (job queued at signal time). All idempotent through the `dedupe_key`.
- Admin user management screen: list/search users, grant/revoke roles (including tournament admin), suspend/reactivate. (Backend endpoints already exist.)
- Toss timeout default once the rulebook rule is confirmed.
- Load test extension: 30 matches plus 200 chat users; security review (XSS, upload abuse, rate limits, cross-room access); browser test for chat.
- **Exit:** Phase 2 definition of done below.

## Edge cases to test
Duplicate send (same `client_id`); message sent while the match state changes; socket reconnect mid-conversation (no gaps, no duplicates); removed or suspended user keeps an open socket (disconnect them); non-member joins a room by guessing the id; batter chatting during submission; editing after 15 min; deleting someone else's message; mention of a non-member; reacting twice; search leaking an inaccessible room's messages; very long or empty message; flood (rate limit); system message ordering versus the scoreboard update; two admins muting the same user; notification dedupe after worker retry.

## Risks
| Risk | Mitigation |
|---|---|
| Digits leaking through chat | Chat lock for the active pair, system messages only after the reveal, test that asserts it |
| Chat and state drifting apart | System messages written in the same transaction as the state change |
| Fan-out load | Redis channel per room, messages small, loadtest with 200 chat users |
| Abuse or inappropriate content | Reports, soft delete, mutes, rate limits; automated image scanning deferred (note) |
| XSS | Plain-text rendering only; no uploads (images were dropped) |
| One access matrix scattered across endpoints | A single `can_read/can_post` service plus a role-by-room test matrix |

## Critical files
- New: `api/app/routers/chat.py`, `notifications.py`, `ws_rooms.py`; `api/app/services/chat.py`, `notify.py`; `api/app/worker.py`; migrations 0003, 0004.
- Modified: `api/app/db/models.py`, `api/app/routers/play.py` (system message hooks, outbox in `commit_match`), `seasons.py`, `matches.py`, `api/app/main.py`, `docker-compose.yml` (worker).
- Web: `app/chat/page.tsx`, `components/chat/*` (MessageList, Composer, MessageItem, PinnedBar, OnlineList, Search, ReportDialog), `lib/useRoom.ts`, `components/NotificationBell.tsx`, `app/notifications/page.tsx`, `app/admin/moderation`, `app/admin/users`, match page tabs, `BottomNav.tsx` (add Chat).
- Reuse: `realtime.client()`, first-message socket auth from `ws.py::_authenticate`, `commit_match`, `ensure_official`/`can_manage`/`is_admin`, `tests/helpers.py::setup_match`, `conftest.py::make_user`, `loadtest/simulate.py`, `lib/useLive.ts` patterns.

## Verification
- API tests: role-by-room access matrix, send/edit/delete rules, dedupe, rate limit, reactions, mentions create notifications, pins, search scoping, mutes, reports, chat lock, system message text per match event, notification dedupe.
- Socket tests (same in-process server pattern as `tests/test_realtime.py`): members receive, non-members get 4403, typing throttled, deleted users disconnected.
- Browser test (Playwright, phone viewport): two players chat in a match, umpire channel invisible to players, announcement banner, system lines appear as an over resolves.
- Load: extend `loadtest.simulate` with chat senders; zero lost or duplicated messages, all watchers in sync.
- Manual: play a full match using only the app.

## Definition of done
- Season chat, match chat and umpire channel work with every feature in the roadmap list.
- Match announcements and notifications fire for every listed event.
- No path (REST, socket, search, system message) exposes hidden digits or a room the user cannot read.
- Tests, lint, browser test and load test green; documented in `docs/PHASE2.md`.

## Sprint 5 outcome
Built: rooms (season, match, umpire) created with each season/match and backfilled; one `can_read`/`can_post` rule used by every endpoint and socket; send (idempotent via `client_id`), cursor history, edit (15 min), soft delete, rate limit (10 per 10 s per room); room socket with presence and periodic re-check that drops users who lose access or log out; Chat tab, Score | Chat | Umpire tabs on the match page; 133 API tests, 2 browser tests.

Decisions made while building:
- A non-member gets **404** from REST and **4403** from the socket for both "no such room" and "not yours", so room ids cannot be probed.
- The access token only gates the socket handshake; a live session keeps its socket until the session ends or access is lost.
- Presence uses heartbeats (20 s) with a 60 s stale limit; a user with two tabs may show offline for up to 20 s after closing one.
- Admins cannot edit other people's messages (only delete).

## Sprint 6 outcome
Built: replies/quotes, reactions (8 emoji, toggle), @mentions (picker; stored as user ids, validated as room members), pinned messages and a pinned bar, pinned announcements, typing indicator (throttled), read receipts ("Seen by"), substring search scoped to rooms the user can read, message reports, admin moderation page (report queue, delete, delete + mute, active mutes, lift, season announcements), per-season mutes that block posting and reacting but not reading. Migration 0004.

Decisions made while building:
- **Images and stickers were dropped** at the owner's request; MinIO, uploads and the sticker set were removed before shipping.
- Search is a case-insensitive substring match (Postgres `ILIKE` with a trigram index), with `%` and `_` matched literally; deleted messages are never searchable.
- `member_ids()` and `readable_room_ids()` are optimised copies of `can_read`; a test asserts they agree for every role and room, so they cannot drift.
- Admins cannot be muted. Muting is admin-only; the match umpire can delete and pin in their own match.
- Mentions are notified in Sprint 7 (the notifications table does not exist yet); for now the mentioned message is highlighted for the person mentioned.
- Search results do not jump to the message in context yet.
