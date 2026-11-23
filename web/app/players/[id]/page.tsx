"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { BattingBowling, MatchHistory, type History, type Totals } from "@/components/league/PlayerStats";
import { api, type Season } from "@/lib/api";

type Stats = { player: { id: number; name: string; player_code: string }; totals: Totals; seasons: ({ season: { id: number; name: string } } & Totals)[]; history: History[] };

function Player() {
  const { id } = useParams<{ id: string }>();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [scope, setScope] = useState("");
  const [d, setD] = useState<Stats | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Season[]>("/seasons").then(setSeasons).catch(() => {}); }, []);
  useEffect(() => {
    api<Stats>(`/players/${id}/stats${scope ? `?season_id=${scope}` : ""}`).then((s) => { setD(s); setErr(null); }).catch((e) => setErr(e.message));
  }, [id, scope]);
  if (!d) return <ErrorText msg={err} />;
  const t = d.totals;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-xl font-semibold">{d.player.name}</h1>
        <p className="text-sm text-muted-foreground">{d.player.player_code}</p>
      </header>
      <select aria-label="Scope" className={inputCls} value={scope} onChange={(e) => setScope(e.target.value)}>
        <option value="">Career</option>
        {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <ErrorText msg={err} />

      <BattingBowling t={t} />

      {d.seasons.length > 1 && (
        <section aria-label="By season" className="space-y-1">
          <h2 className="font-medium">By season</h2>
          <ul className="divide-y rounded-lg border text-sm">
            {d.seasons.map((s) => <li key={s.season.id} className="flex justify-between p-3"><span>{s.season.name}</span><span className="text-muted-foreground">{s.matches} m · {s.runs} runs · {s.wickets} wkts</span></li>)}
          </ul>
        </section>
      )}

      <MatchHistory history={d.history} matchHref={(id) => `/matches/${id}`} />
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Player /></RequireAuth>;
}
