"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, type Season, type Team } from "@/lib/api";

type Row = { rank: number; player: { id: number; name: string } | null; team: { id: number; name: string } | null; value: number; detail: string };
type Board = { season: { id: number; name: string }; categories: { key: string; title: string; rows: Row[] }[]; minimums: { strike_rate_balls: number; economy_balls: number } };

const fmt = (key: string, v: number) => (key === "best_strike_rate" || key === "best_economy" ? v.toFixed(2) : key === "best_win_pct" ? `${v}%` : String(v));

function Leaderboards() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [teams, setTeams] = useState<Team[]>([]);
  const [team, setTeam] = useState("");
  const [data, setData] = useState<Board | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((s) => { setSeasons(s); setSid(String((s.find((x) => x.status === "active") ?? s[0])?.id ?? "")); }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    if (!sid) return;
    /* eslint-disable react-hooks/set-state-in-effect -- reset and fetch when the season changes */
    setTeam("");
    api<Team[]>(`/seasons/${sid}/teams`).then(setTeams).catch((e) => setErr(e.message));
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [sid]);
  useEffect(() => {
    if (!sid) return;
    api<Board>(`/seasons/${sid}/leaderboards${team ? `?team_id=${team}` : ""}`).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(e.message));
  }, [sid, team]);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Leaderboards</h1>
      <div className="flex gap-2">
        <select aria-label="Season" className={inputCls} value={sid} onChange={(e) => setSid(e.target.value)}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select aria-label="Team" className={inputCls} value={team} onChange={(e) => setTeam(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      </div>
      <ErrorText msg={err} />
      {data && data.categories.every((c) => c.rows.length === 0) && <p className="text-sm text-muted-foreground">No statistics yet. They appear once matches are played.</p>}
      {data?.categories.map((c) => (
        <section key={c.key} aria-label={c.title} className="space-y-1">
          <h2 className="font-medium">{c.title}</h2>
          {c.key === "best_strike_rate" && <p className="text-xs text-muted-foreground">At least {data.minimums.strike_rate_balls} balls faced.</p>}
          {c.key === "best_economy" && <p className="text-xs text-muted-foreground">At least {data.minimums.economy_balls} balls bowled.</p>}
          {c.rows.length === 0 ? <p className="text-sm text-muted-foreground">Nobody yet.</p> : (
            <ol className="divide-y rounded-lg border">
              {c.rows.map((r) => (
                <li key={`${r.player?.id ?? r.team?.id}`} className="flex items-center gap-3 p-3 text-sm">
                  <span className="w-5 text-muted-foreground">{r.rank}</span>
                  <span className="min-w-0 flex-1">
                    {r.player ? <Link href={`/players/${r.player.id}`} className="font-medium underline">{r.player.name}</Link> : <Link href={`/teams/${r.team?.id}`} className="font-medium underline">{r.team?.name}</Link>}
                    <span className="block truncate text-xs text-muted-foreground">{r.player ? `${r.team?.name ?? ""} · ` : ""}{r.detail}</span>
                  </span>
                  <span className="text-base font-semibold">{fmt(c.key, r.value)}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Leaderboards /></RequireAuth>;
}
