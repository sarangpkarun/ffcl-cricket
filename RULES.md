# FFCL Game Rules (engine spec)

Source of truth for the engine. Every example below becomes a unit test. All values are stored in the versioned `rule_sets` config, not hardcoded.

## Match format
| Setting | Value |
|---|---|
| Overs | 7 |
| Wickets | 7 |
| Balls per over | 6 |
| Max overs per bowler | 2 |
| Players per team | 7 |
| Digits | 1 to 6 only (0 invalid) |

## Over types
| Over | Type | Batting digits | Bowling digits |
|---|---|---|---|
| 1, 3, 4, 5, 7 | Normal | Any digits 1-6 | One digit may appear 3 times, every other digit at most 2 |
| 2 | Bowling powerplay (batter restricted) | 5 and 6 each exactly once, other four free | Normal limit |
| 6 | Batting powerplay (bowler restricted) | Any digits 1-6 | 5 and 6 each exactly once, other four follow the normal limit |

Each side submits six digits per over. In a powerplay the 5 and 6 may be in any positions, so the other four digits can only be 1-4.

> Assumptions to confirm: the free four digits of a restricted batter are unlimited (1-4); the free four of a restricted bowler follow the normal repeat limit.

## Ball resolution
- Batter digit equals bowler digit: **wicket**. The bowler gets credit. Runs 0.
- Otherwise: **runs = batter digit**.
- **PENDING rulebook confirmation:** the runs-equal-batter-digit rule. Examples in the spec (2 vs 5 gives 2, 4 vs 1 gives 4, 6 vs 3 gives 6) fit it.

## Innings and result
- Innings ends after 7 overs, 7 wickets, or (second innings) when the target is passed.
- Target = first innings total + 1.
- Equal totals: tie. Higher total wins (by wickets remaining in the chase, or by runs when defending).
- Penalty runs and wickets count in team totals only. Never in individual batting or bowling stats.
- Submissions are private. Neither side nor spectators see digits before the umpire locks and reveals.

## Toss timeout
- Both captains must answer the toss. The wait is `toss_timeout_minutes` after the scheduled start (default **15**, a rule-set setting from 1 to 240).
- Nothing happens automatically. When the wait is over and the toss is not settled, the match umpire (or an admin of the season) may declare the team whose captain did not answer absent. That is an ordinary **walkover**: the other team is awarded the match, the table and chat are updated, and an admin can reverse it.
- Before the wait is over, or once the toss is confirmed, the action is refused. A match with no scheduled start cannot use it; the umpire declares a walkover with a reason instead.

## Worked examples

### A. Bowling digit validation (normal over)
| # | Digits | Valid | Reason |
|---|---|---|---|
| A1 | 1,2,3,4,5,6 | yes | all distinct |
| A2 | 1,1,1,2,2,3 | yes | one digit x3, another x2 |
| A3 | 1,1,1,2,2,2 | no | two digits used 3 times |
| A4 | 1,1,1,1,2,3 | no | digit used 4 times |
| A5 | 1,1,2,2,3,3 | yes | none above 2 |
| A6 | 1,2,3,4,5 | no | only five digits |
| A7 | 1,2,3,4,5,0 | no | digit 0 |
| A8 | 1,2,3,4,5,7 | no | digit 7 |

### B. Bowling powerplay (over 2): BATTING digits restricted
| # | Batting digits | Valid | Reason |
|---|---|---|---|
| B1 | 5,6,1,2,3,4 | yes | 5 and 6 once each |
| B2 | 5,5,6,1,2,3 | no | 5 twice |
| B3 | 1,2,3,4,1,2 | no | missing 5 and 6 |
| B4 | 1,5,2,6,3,4 | yes | any order |
| B5 | 5,6,1,1,1,1 | yes | free digits unlimited for batter |
| B6 | 6,6,6,6,6,6 | no | 6 six times |
Bowling digits in over 2 follow the normal limit (A examples).

### C. Batting powerplay (over 6): BOWLING digits restricted
| # | Bowling digits | Valid | Reason |
|---|---|---|---|
| C1 | 6,5,2,2,1,4 | yes | 5 and 6 once each, 2 twice |
| C2 | 6,6,5,1,2,3 | no | 6 twice |
| C3 | 1,1,1,2,2,3 | no | missing 5 and 6 |
| C4 | 5,6,1,1,1,2 | yes | one digit x3 |
| C5 | 5,6,1,1,1,1 | no | digit used 4 times |
Batting digits in over 6 are unrestricted.

### D. Normal batting (any 1-6, six digits)
| # | Batting digits | Valid |
|---|---|---|
| D1 | 6,6,6,6,6,6 | yes |
| D2 | 1,2,3,4,5 | no (five digits) |
| D3 | 1,2,3,4,5,0 | no (digit 0) |

### E. Ball outcomes
| # | Batter | Bowler | Result |
|---|---|---|---|
| E1 | 2 | 5 | 2 runs |
| E2 | 4 | 1 | 4 runs |
| E3 | 6 | 3 | 6 runs |
| E4 | 3 | 3 | wicket, bowler credit |
| E5 | 5 | 5 | wicket, bowler credit |
| E6 | 1 | 6 | 1 run |

### F. Over and innings
| # | Situation | Outcome |
|---|---|---|
| F1 | Batter 1,2,3,4,5,6 vs bowler 6,5,4,3,2,1 | no equal pairs, 21 runs, 0 wickets |
| F1b | Batter 1,2,3,4,5,6 vs bowler 1,2,3,4,5,6 | six wickets, 0 runs |
| F2 | Batting 7 wickets lost in over 4 | innings ends, all out |
| F3 | Chase passes target mid-over | match ends immediately, chasing team wins |
| F4 | Both totals equal after 7 overs | tie |
| F5 | Penalty +6 runs | team total +6, no player stats change |
| F6 | Penalty wicket | team wickets +1, no bowler credit |
| F7 | Bowler asked to bowl a third over | rejected |
| F8 | Submission from unregistered phone | rejected |
| F9 | Submission after lock | rejected |
| F10 | Duplicate submission for same over and role | rejected (idempotent) |
| F11 | Umpire correction of a ball | new event revision, scorecard recomputed, audit logged |

Machine-readable versions of these examples live in `api/tests/fixtures/rules_examples.json` and are run by `api/tests/test_engine_examples.py`.
