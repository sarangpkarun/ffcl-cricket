"use client";

import { useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import Link from "next/link";
import { Leaderboards, type LeaderBoard } from "@/components/league/Leaderboards";
import { api, type Season, type Team } from "@/lib/api";


function LeaderboardsPage() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [teams, setTeams] = useState<Team[]>([]);
  const [team, setTeam] = useState("");
  const [data, setData] = useState<LeaderBoard | null>(null);
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
    api<LeaderBoard>(`/seasons/${sid}/leaderboards${team ? `?team_id=${team}` : ""}`).then((d) => { setData(d); setErr(null); }).catch((e) => setErr(e.message));
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
      <p className="text-sm"><Link className="underline" href="/insights">Season insights</Link> · <Link className="underline" href="/history">Past seasons</Link></p>
      <ErrorText msg={err} />
      {data && <Leaderboards data={data} playerHref={(id) => `/players/${id}`} teamHref={(id) => `/teams/${id}`} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><LeaderboardsPage /></RequireAuth>;
}
