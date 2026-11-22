# FFCL Phase 3: Tournament Management (plan)

**Deliverable on approval:** write this document to `/home/sarang/Documents/FFCL/docs/PHASE3.md` (the only file created before implementation starts).

## Context
Phases 1 and 2 made a single match playable and social. A league is more than matches: someone has to build the fixture list, publish it, keep the table, record who no-showed, crown a champion and remember it next season. Today admins create each match by hand, nothing computes standings, and there are no player or team statistics. Phase 3 turns the app from "a match engine" into "a league": **a whole season can be set up, played and archived without a spreadsheet.**

What already exists and is reused: the append-only ball events and `recompute()` in `api/app/services/scoring.py` (the one place a match result is derived), `say()`/`notify()`/the outbox for announcements and notifications, the admin router pattern in `routers/admin_users.py`, audit logging, versioned `rule_sets` pinned on each match, `loadtest/world.py`, and the test helpers (`tests/helpers.py`, `conftest.py`).

## Decisions
Answered by you:
| Question | Decision |
|---|---|
| Points | **Win 2, tie 1, loss 0.** Configurable per season in the rule set. |
| Format | **Round robin, then semi-finals and final** (top four qualify). Single or double round robin is a setting. |
| Tie-break order | **Points, then net run rate, then wins, then head-to-head, then team name** (so the table is always fully ordered). Net run rate counts a team that is all out as having faced the full 7 overs. |
| Walkover | **Present team gets the full win points, absent team gets 0.** No scores are recorded, so batting and bowling stats are untouched and net run rate ignores the match. |

Defaults I chose (tell me if any are wrong; each is a setting):
| Question | Default |
|---|---|
| Knockout match ends tied | The team that finished higher in the league advances. (Replay and super over are the alternatives.) |
| Abandoned match / no result | 1 point each, ignored by net run rate and stats. Or reschedule it as a replay. |
| Umpire duty missed | The team that supplied the umpire loses **1 point** (the roadmap's rule). Admin or umpire records it; admins can reverse it. |
| Player of the match | Chosen by the umpire (or an admin) from either team, with the app suggesting the best performer. |
| Stat qualifiers | Best strike rate needs 12 balls faced, best economy needs 2 overs bowled (both configurable). |
| Who sees what | Fixtures, table and leaderboards are readable by every signed-in user now; Phase 4 opens them to the public. Unpublished fixtures are visible to admins only. |
| Still open from before | **Toss timeout when a captain is absent.** It becomes much simpler once walkovers exist (it can end in one), but I still need the rulebook wording. |

## Architecture
- **Derived, not stored, wherever possible.** The table and all statistics are computed from the immutable ball events and a small results ledger, so a correction or a changed rule recalculates everything and nothing can drift. Never edit a stored total.
- **One results ledger.** A `match_results` row is written (and rewritten) only by `finish_match()`, called from the same place `recompute()` runs. Normal results, ties, walkovers and abandonments all produce one row. The table reads only from this ledger plus point adjustments.
- **Pure engines, tested to death.** Fixture generation, knockout seeding and the standings table (net run rate, tie-breaks, head-to-head) are plain Python with no database, covered by worked examples and property tests, exactly like the game engine.
- **Config in the rule set.** Points, tie-break order, qualifiers, duty penalty and knockout size live in `rule_sets.config` (versioned; each match keeps the version it started under). Standings use the season's current version, so changing points mid-season reprices the whole table consistently.
- **Statistics by SQL over the latest ball revisions**, restricted to matches with a normal result, cached in Redis for 30 seconds. Corrections show up immediately because nothing is pre-aggregated.
- **Fixtures are drafts until published.** Publishing notifies everyone involved; rescheduling a published match notifies again.
- **Archived seasons are read-only** (one guard shared by every write route).

## Data model (migrations 0006-0009)
- `stages(id, season_id, kind round_robin|knockout, name, ord, config jsonb)`; matches gain `stage_id`, `round_label`, `published_at`.
- `match_results(match_id unique, result_type normal|tie|walkover|abandoned|no_result, winner_team_id, a_runs, a_balls_faced, a_wickets, b_runs, b_balls_faced, b_wickets, decided_at)`.
- `point_adjustments(id, season_id, team_id, match_id null, points int, kind umpire_duty|conduct|manual, reason, created_by, voided_at)`.
- `umpire_duties(match_id unique, umpire_id, team_id, status assigned|performed|missed|replaced, note, decided_by)`.
- `match_awards(match_id, kind potm, user_id, chosen_by)`; unique per match and kind.
- `roster_changes(id, team_id, out_user_id, in_user_id, reason, status pending|approved|rejected, requested_by, decided_by, decided_at)`.
- `phone_change_requests(id, user_id, new_phone, reason, status pending|approved|rejected|completed, decided_by)`.
- Match status gains `abandoned`; Match gets `result_type` through the ledger.

## Sprints (about 5 weeks)

### Sprint 9: Fixtures and scheduling (week 1) ✅ done
- Migration 0006; `engine/fixtures.py`: round-robin generator (circle method, odd team counts get byes, optional second leg, home/away balanced), plus a scheduler that spreads matches over dates and time slots with no team playing twice at once.
- Umpire suggestion: each team supplies umpires evenly; never someone playing in that match or at the same time.
- API: create stages, generate (preview first, then save as unpublished), edit/reschedule/delete drafts, publish, conflict checks (team or umpire double-booked), notifications ("fixtures published", "match rescheduled").
- UI: **Fixtures** page (Upcoming / Live / Completed, team filter, status badges) and an admin **Season setup** wizard (teams, stages, generate, review, publish).
- **Exit:** an admin generates a full round robin for 6 teams, adjusts it and publishes; players see only published matches.

### Sprint 10: Results ledger, points table, knockouts (week 2) ✅ done
- Migration 0007; `finish_match()` hooked into `recompute()` so every completion, correction and withdrawn result updates the ledger.
- `engine/standings.py`: points, net run rate, tie-breaks (including head-to-head among the tied group), point adjustments.
- Knockouts: generate semi-finals from the top four (1v4, 2v3), the final is created automatically when both semis finish (idempotent), tie rule applied, season champion recorded.
- API and UI: **Points table** page (position, played, won, tied, lost, points, NRR, adjustments), highlights qualifying places, per-team form guide.
- **Exit:** play a full 4-team season; the table is correct after corrections (including a flipped result) and the final is created without admin action.

### Sprint 11: Walkovers, abandonment, umpire duty, adjustments (week 3) ✅ done
- Migration 0008; umpire or admin declares a walkover (who was absent) or abandons a match (reason, replay option); both announce in the match chat, notify everyone and write the ledger row; no ball events are created.
- Umpire duty records are created from the umpire assignment, marked performed when the umpire runs the match, or missed by admin or umpire (which creates the -1 point adjustment). Admins can reverse it; every step is audited.
- Admin **Points adjustments** screen (add, list, void).
- **Exit:** a walkover, an abandoned match and a missed duty each change the table exactly as configured and can be reversed.

### Sprint 12: Statistics and leaderboards (week 4)
- `services/stats.py`: batting (runs, balls, 4s, 6s, strike rate, highest score, innings, dismissals), bowling (balls, runs, wickets, economy, best figures), team (win %, NRR), all from the latest ball revisions of normal-result matches, with the qualifier thresholds.
- Leaderboards: most runs, most wickets, highest score, best strike rate, best economy, most sixes, most fours, most player-of-the-match awards, best win percentage; filters by season, team and player.
- Player of the match: umpire/admin picks (with suggestion); migration 0008 table.
- UI: **Leaderboards** page, **Player** page (season and career, match history), team statistics block on the team page.
- **Exit:** stats reconcile exactly with scorecards (sum of player runs equals team totals minus penalties), including after corrections.

### Sprint 13: Approvals, history, rules and exports (week 5)
- Migration 0009; **roster changes**: captains request a replacement, admins approve; blocked if the outgoing player is in an upcoming lineup, the incoming player is already in a team, or the roster would exceed 7.
- **Phone number changes**: a player requests, an admin approves, then the player proves the new number by OTP before it replaces the old one (the old number is freed and the change is audited).
- **Season archive and history**: archive makes the season read-only; a Season history page shows past champions, final tables and top performers.
- **Rules versions screen**: create a new version (copy and edit), see differences from the previous one, apply it to a season; matches keep the version they started under.
- **Audit log viewer** (filter by person, action, record, date) and **CSV exports** (fixtures, table, player statistics).
- Final pass: load test with a full season, security review addendum.
- **Exit:** Phase 3 definition of done below.

## Edge cases to test
Odd number of teams (byes); a team entered twice in one slot; umpire who is also playing; rescheduling a match after publish; a result corrected after the table was published (including a win becoming a loss, a tie becoming a win, and a completed match reopening); tie on points among three teams (head-to-head mini-table); all-out net run rate; chase finished early (actual balls); walkover then the "absent" team protests (reversal); abandoning a match with balls already played; duty marked missed twice; a player transferred mid-season (stats stay with the matches they played, not the team they are on now); statistics when a ball is corrected after the leaderboard was cached; archiving a season with unfinished matches (must refuse); phone number requested that already belongs to someone else; two admins approving the same request at once.

## Risks
| Risk | Mitigation |
|---|---|
| Table or stats drift from the real results | Nothing is stored that is not derived; a test rebuilds the table from scratch and compares it after every kind of correction |
| Tie-break rules are subtle (head-to-head in a 3-way tie) | Pure engine with worked examples from real cricket tables and property tests (order is total and deterministic) |
| Fixture generator produces unplayable schedules | Preview before saving, conflict checks on every edit, and a test that no team plays twice in a slot |
| Leaderboard queries slow down as seasons accumulate | Indexes on ball events by innings and over, 30-second cache, load test with a full season |
| Rule changes mid-season confuse people | Rule versions are explicit, shown with differences, and matches keep the version they started under |
| Approvals (roster, phone) abused | Every request is audited, limited to one pending per person, and approval re-checks the conditions at decision time |

## Critical files
- New: `api/app/engine/fixtures.py`, `standings.py`, `knockout.py`; `api/app/services/results.py` (`finish_match`), `stats.py`, `schedule.py`; routers `fixtures.py`, `standings.py`, `stats.py`, `walkovers.py`, `roster.py`, `phone_changes.py`, `admin_rules.py`, `admin_audit.py`, `exports.py`; migrations 0006-0009.
- Modified: `api/app/db/models.py`, `api/app/services/scoring.py` (`recompute` calls `finish_match`), `api/app/routers/matches.py` and `seasons.py` (publish, archive guard), `api/app/services/match_events.py` (walkover and abandon announcements), `api/app/services/notify.py` (new kinds), `api/app/engine/rules.py` (points, tie-breaks, qualifiers in the default rule set).
- Web: `app/fixtures`, `app/standings`, `app/leaderboards`, `app/players/[id]`, `app/seasons/history`, admin `season setup`, `walkovers`, `adjustments`, `roster-changes`, `phone-requests`, `rules`, `audit`; `BottomNav` gets Fixtures and Table.
- Reuse: `recompute()`, `say()`/`notify()`/outbox, `admin_users.py` structure, `tests/helpers.py::setup_match` and `play`, `loadtest/world.py`, `engine/innings.py::summarize_innings` (runs and balls faced feed net run rate and the ledger).

## Verification
- Engine unit tests: fixtures (every pair meets, no team twice per round, byes), knockout seeding, standings (points, NRR with all-out quota, 2- and 3-way head-to-head, adjustments, deterministic order) with worked examples and property tests.
- API tests: ledger written for every result type and updated by corrections, withdrawn results removed, table equals the table rebuilt from scratch, walkover/abandon/duty effects and reversals, publish visibility, conflicts, stats reconcile with scorecards, approvals and their re-checks, archive read-only, CSV contents.
- Browser tests (phone viewport): admin generates and publishes fixtures; a player sees the fixtures; a played match moves the table; leaderboards and a player page render; a roster change and a phone change complete.
- Load test: a 6-team double round robin plus knockouts played by the simulator, then standings and leaderboard timings and a rebuild-from-scratch comparison.
- Manual: run a short season end to end using only the app.

## Definition of done
- An admin builds, publishes, runs and archives a complete season (round robin, semi-finals, final) inside the app.
- The points table, net run rate, tie-breaks, walkovers, abandonments and umpire-duty penalties behave exactly as configured and can be reversed with an audit trail.
- Leaderboards and player pages reconcile with the scorecards, including after corrections.
- Roster and phone-number changes need approval; archived seasons cannot be modified.
- Tests, lint, browser tests and the load test are green; documented in `docs/PHASE3.md`.

## Sprint 9 outcome
Built:
- **Fixture engine** (`engine/fixtures.py`, pure): round-robin by the circle method (odd team counts give each team one bye per leg; optional second leg with home and away swapped), a slot scheduler (matches per slot, rest between a team's matches, rounds kept in order, local times with weekdays) and a fair umpire plan (never someone in either team, never playing or umpiring at the same time, duties shared evenly between supplying teams, then between people). 195 engine tests including a hand-worked 4-team case.
- **Draft then publish.** Generated matches are drafts (`published_at` empty) visible only to admins, in every view: match list, match page, live view, chat rooms, lineup, and nobody can start a draft. Publishing sets them live, notifies each team's members once ("New fixtures are published" with that team's next match) and tells umpires, and is safe to repeat. Matches an admin creates by hand are published immediately, as before.
- **Clash checks** on every create and reschedule: a team, an umpire, or an umpire who is playing, within 90 minutes of another match. The organiser can override ("Save anyway"), which is audited. Rescheduling a published match posts a line in the match chat and notifies both teams and the umpire.
- **API**: preview (saves nothing), generate (creates the stage and draft matches, with chat rooms), replace unpublished drafts, publish (all, one stage, or chosen matches), delete drafts (published matches can never be deleted), fixture list with filters, stages list.
- **Screens**: **Fixtures** page (Upcoming / Live / Completed, team filter, status badges, admin "Show drafts") replacing Matches in the bottom navigation, and an admin **Fixtures setup** page (format, preview with warnings, create drafts, review and edit each draft, two-step publish).
- Migration 0006 (stages, round label, published date; existing matches backfilled as published).

Bugs the tests caught while building: the first home/away heuristic was unbalanced for every league above two teams (replaced by an Euler-circuit orientation, which is provably within one); the draft umpire dropdown could display "No umpire" for an assigned umpire when the umpire list was capped.

Deliberate limits:
- The admin umpire choices list the first 100 umpires (search comes with the People screen); generation itself uses all of them.
- Knockout stages arrive in Sprint 10; this sprint generates the league stage only.
- Time zone is entered as text (defaults to the browser's); there is no per-league setting yet.

## Sprint 10 outcome
Built:
- **Results ledger** (`match_results`, migration 0007): one row per finished match with both sides' runs, balls faced and all-out flags. It is written by `sync_ledger()` inside `recompute()`, so every completion, correction, penalty, voided penalty and withdrawn result rewrites it in the same transaction (a withdrawn result removes the row). Existing completed matches were backfilled with the new `POST /admin/results/rebuild` tool (207 matches in the dev database), which is also the repair tool.
- **Standings engine** (`engine/standings.py`, pure): points, played/won/lost/tied, form guide, point adjustments, and net run rate using exact fractions (an all-out innings counts as the full 7 overs; walkovers, abandonments and no-results never touch it). Tie-breaks follow the rule set's order, default **points, net run rate, wins, head-to-head, name**: head-to-head is a mini-league among the teams still level and is re-run on whoever remains level; the order is always total and independent of the order results arrive. 23 engine tests, including hand-calculated net run rates and properties (every match hands out exactly two points, results order does not matter).
- **Knockouts** (`engine/knockout.py`, `services/results.py`): `POST /seasons/{id}/knockouts/generate` seeds the top four 1 v 4 and 2 v 3 (or the top two straight into a final), published at once with umpires who are not playing, and refuses until the league is finished unless the admin overrides. The **final is created automatically** when both semi-finals finish, exactly once, dated the day after the last semi. If a correction changes a semi-final before the final starts, the final's teams are updated (lineups cleared, people notified, audited); if a semi result is withdrawn the final goes on hold and returns when the semi is decided again; once the final has started such a correction is refused (HTTP 409) and nothing changes. A tied knockout is won by the higher league seed, and is still recorded honestly as a tie. Winning the final records the **season champion** (announced in the season chat and to the winners; a correction can change it).
- **Table and bracket API and screens**: `GET /seasons/{id}/standings` and `/bracket`; a **Table** page (position, played, won, lost, tied, points, net run rate, form chips, qualifying places marked, the tie-break order spelled out, champion banner, knockout bracket) and a knockouts section on the admin setup page. "Table" is now a tab in the bottom navigation.

Decisions and notes:
- Which matches count: the league stage and hand-made matches without a stage. Knockout matches never affect the league table.
- Point adjustments are read by the table now (voided ones ignored); the screens to create them come in Sprint 11. Walkover and abandonment points are already in the engine and the rule set; Sprint 11 writes the ledger rows.
- The test database is now reset with `DROP SCHEMA` instead of per-table drops, because the champion link makes seasons and teams reference each other.
- Only two or four qualifiers are supported; anything else is refused.

## Sprint 11 outcome
Built:
- **Walkovers**: an admin or the match umpire declares which team did not turn up, only before the match starts (scheduled, toss or ready). The present team is awarded the win (2 points), the absent team gets 0, no scores or ball events exist, and net run rate and statistics ignore the match. The match chat gets a system line and both teams and the umpire are notified. A captain cannot declare one for their own team.
- **Abandonment**: any official can abandon a match that has not finished. If nothing was bowled the ledger row is `abandoned`; if balls were played it is `no_result` and the balls are kept. Either way each team gets 1 point and net run rate ignores it. Optionally a **draft replay** is created (same teams, umpire and optional time); a replayed knockout match keeps its bracket label so the final still appears when the replay is played. An abandoned match no longer holds up "league complete".
- **Reversal** (admins only, with a reason): the match returns to the status it had before. A live match comes back paused so the umpire resumes on purpose. An unpublished replay is removed; a published replay blocks the reversal (HTTP 409). Reversing a walkover in a semi-final updates or holds the final, and is refused once the final has started. Every declaration and reversal is kept in `match_declarations` and audited.
- **Umpire duty** (`umpire_duties`): created and kept in step with the umpire assignment (changing the umpire marks the old duty `replaced`), marked `performed` when the umpire runs the match, and marked `missed` by an admin or the umpire who stepped in. A missed duty creates a point adjustment of minus `umpire_duty_penalty` (default 1) against the team that supplied the umpire; reversing it voids the adjustment.
- **Points adjustments**: add (manual or conduct, plus or minus up to 50, with a reason), list and void, all audited, with the affected team notified. The table already read them.
- **Screens**: walkover, abandon and reverse controls in the umpire console (driven by `live.match.declared`), and admin **Points adjustments** and **Umpire duties** pages linked from the admin home.
- Migration 0008 (declarations, duties; duty rows backfilled for existing matches).

Tests: 11 new API tests (walkover effects and validation, reversal, abandonment before and during a match, replays, knockout interactions) and one browser test (walkover, reversal, abandonment, adjustment and missed duty).

Deliberate limits:
- A match in progress can be abandoned but not given a walkover.
- A walkover reversed after other results depended on it is only blocked by the final-started rule; there is no wider dependency check.
