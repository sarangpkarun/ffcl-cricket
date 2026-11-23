import { headers } from "next/headers";
import type { Bracket, FixtureTeam, Live, Standings, TableRow } from "@/lib/api";
import type { History, Totals } from "@/components/league/PlayerStats";
import type { PlayerAnalytics, SeasonAnalytics, TeamAnalytics } from "@/lib/analytics";
import type { LeaderBoard } from "@/components/league/Leaderboards";

/** Server-side reads of the public API. Pages stream this data at request time, so it is always fresh. */
const API = process.env.API_INTERNAL_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const SITE = process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3100";

export type PubSeason = { id: number; name: string; slug: string; status: string; starts_on: string | null };
export type PubFixture = {
  id: number; match_no: number; round_label: string | null; status: string; paused: boolean; scheduled_at: string | null;
  team_a: FixtureTeam; team_b: FixtureTeam; umpire: string | null; result: string | null; winner_team_id: number | null;
};
export type Person = { id: number | null; name: string; player_code: string };
export type SeasonListItem = PubSeason & { teams: number; matches: number; champion: string | null };
export type Overview = {
  season: PubSeason; champion: { id: number; name: string } | null; live: PubFixture[]; next: PubFixture[]; latest: PubFixture[];
  table: TableRow[]; qualifiers: number; league_complete: boolean;
  leaders: Record<"most_runs" | "most_wickets", { rank: number; player: { id: number | null; name: string } | null; team: { id: number; name: string } | null; value: number; detail: string }[]>;
};
export type PubLeaders = LeaderBoard & { season: { id: number; name: string } };
export type PubTeam = {
  team: { id: number; name: string; color: string | null }; season: PubSeason; members: { player: Person; captain: boolean }[];
  table: TableRow | null; win_pct: number | null; best: Record<string, { player: Person | null; value: number; detail: string } | null>;
  players: ({ player: Person | null; runs: number; wickets: number; matches: number })[]; fixtures: PubFixture[];
};
export type PubPlayer = { player: Person; season: PubSeason; totals: Totals; history: History[]; other_seasons: PubSeason[] };
export type PubMatch = { season: PubSeason; round_label: string | null; scheduled_at: string | null; live: Live };
export type PubHistory = {
  season: PubSeason; champion: { id: number; name: string } | null;
  table: { position: number; team: string; played: number; won: number; lost: number; points: number; nrr: number }[];
  top_batter: { player: Person; value: number } | null; top_bowler: { player: Person; value: number } | null;
  most_awards: { player: Person; value: number } | null; matches: number; teams: number;
};
export type PubRules = { season: PubSeason; sections: { title: string; items: string[] }[] };
export type PubBracket = Bracket;
export type PubStandings = Standings;

/** GET a public endpoint. Returns null when it is not found (the page then shows "not found"). */
export async function pub<T>(path: string): Promise<T | null> {
  const fwd = (await headers()).get("x-forwarded-for"); // so the API rate-limits the visitor, not this server
  const res = await fetch(`${API}/public${path}`, { headers: fwd ? { "x-forwarded-for": fwd } : {} });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`Could not load ${path} (${res.status})`);
  return (await res.json()) as T;
}

/** Plain GET for metadata and sitemap code that runs outside a request. */
export async function pubPlain<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}/public${path}`);
    return res.ok ? ((await res.json()) as T) : null;
  } catch {
    return null;
  }
}

export type { PlayerAnalytics, SeasonAnalytics, TeamAnalytics };
