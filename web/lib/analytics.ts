export type OverType = "normal" | "bowling_pp" | "batting_pp";
export const TYPE_LABEL: Record<OverType, string> = { normal: "Normal overs", bowling_pp: "Bowling powerplay", batting_pp: "Batting powerplay" };
export const TYPE_ORDER: OverType[] = ["normal", "bowling_pp", "batting_pp"];

export type ByType<K extends string> = Record<OverType, { balls: number; runs: number; wickets: number } & Record<K, number>>;
export type WormPoint = { ball: number; over: number; runs: number; wicket: boolean };
export type OverRow = { over: number; type: OverType; runs: number; wickets: number; balls: number };
export type InningsAnalytics = {
  number: number; team: { id: number; name: string | null }; total: number; ball_runs: number; penalty_runs: number; wickets: number; balls: number;
  run_rate: number; target: number | null; overs: OverRow[]; worm: WormPoint[]; by_type: ByType<"run_rate">;
};
export type MatchAnalytics = { match_id: number; overs_in_match: number; balls_per_over: number; innings: InningsAnalytics[]; biggest_over: OverRow | null; over_types: Record<string, OverType> };

export type Record2 = { played: number; won: number; pct: number | null };
export type TeamAnalytics = {
  team: { id: number; name: string; color: string | null };
  played: number; won: number; lost: number; tied: number; batting_first: Record2; chasing: Record2;
  runs_for: number; runs_against: number; average_for: number | null; average_against: number | null; highest: number | null; lowest: number | null;
  batting_by_type: ByType<"run_rate">; bowling_by_type: ByType<"economy">;
  toss: { won: number; lost: number; chose_bat: number; chose_bowl: number; win_pct_after_winning: number | null; win_pct_after_losing: number | null };
};
export type DigitCounts = { total: number; counts: Record<string, number>; percent: Record<string, number>; most_used: number | null };
export type SeasonAnalytics = {
  season: { id: number; name: string; slug: string; status: string };
  summary: {
    matches: number; decided: number; ties: number; average_first_innings: number | null; average_second_innings: number | null;
    highest_total: number | null; lowest_total: number | null; bat_first_wins: number; chase_wins: number; bat_first_pct: number | null; chase_pct: number | null;
    toss: { matches: number; toss_winner_won: number; toss_winner_pct: number | null; chose_bat: number; chose_bowl: number };
    by_type: ByType<"run_rate"> & Record<OverType, { wickets_per_over: number }>;
  };
  teams: TeamAnalytics[]; digits_available: boolean; digits: { batting: DigitCounts; bowling: DigitCounts } | null;
};
export type PlayerAnalytics = {
  player: { id: number; name: string; player_code: string }; season_id: number | null;
  batting_by_type: ByType<"strike_rate"> & Record<OverType, { outs: number }>; bowling_by_type: ByType<"economy">;
  form: { match_id: number; match_no: number; runs: number; balls: number; out: boolean; bowl_balls: number; runs_conceded: number; wickets: number; team: string | null; opponent: string | null }[];
  versus_bowlers: { user_id: number | null; name: string | null; balls: number; runs: number; outs: number; strike_rate: number }[];
  versus_batters: { user_id: number | null; name: string | null; balls: number; runs: number; wickets: number; economy: number }[];
  digits_available: boolean; digits: { batting: DigitCounts; bowling: DigitCounts } | null;
};
