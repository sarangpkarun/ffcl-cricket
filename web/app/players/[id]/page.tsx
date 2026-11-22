"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, type Season } from "@/lib/api";

type Totals = {
  matches: number; innings: number; runs: number; balls: number; fours: number; sixes: number; outs: number; not_outs: number; highest: number;
  strike_rate: number; average: number | null; bowl_innings: number; overs: string; runs_conceded: number; wickets: number; economy: number;
  best_bowling: string | null; potm: number;
};
type History = {
  match_id: number; match_no: number; round_label: string | null; against: string | null; team: string | null; won: boolean | null;
  batted: boolean; runs: number; balls: number; out: boolean; bowled: boolean; bowl_balls: number; runs_conceded: number; wickets: number; potm: boolean;
};
type Stats = { player: { id: number; name: string; player_code: string }; totals: Totals; seasons: ({ season: { id: number; name: string } } & Totals)[]; history: History[] };

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border p-2 text-center"><p className="text-lg font-semibold">{value}</p><p className="text-xs text-muted-foreground">{label}</p></div>;
}

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

      <section aria-label="Batting" className="space-y-2">
        <h2 className="font-medium">Batting</h2>
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Matches" value={t.matches} />
          <Stat label="Runs" value={t.runs} />
          <Stat label="Highest" value={t.highest} />
          <Stat label="Strike rate" value={t.strike_rate.toFixed(2)} />
          <Stat label="Average" value={t.average === null ? "–" : t.average.toFixed(2)} />
          <Stat label="4s / 6s" value={`${t.fours} / ${t.sixes}`} />
        </div>
      </section>
      <section aria-label="Bowling" className="space-y-2">
        <h2 className="font-medium">Bowling</h2>
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Overs" value={t.overs} />
          <Stat label="Wickets" value={t.wickets} />
          <Stat label="Economy" value={t.economy.toFixed(2)} />
          <Stat label="Runs given" value={t.runs_conceded} />
          <Stat label="Best" value={t.best_bowling ?? "–"} />
          <Stat label="Player of match" value={t.potm} />
        </div>
      </section>

      {d.seasons.length > 1 && (
        <section aria-label="By season" className="space-y-1">
          <h2 className="font-medium">By season</h2>
          <ul className="divide-y rounded-lg border text-sm">
            {d.seasons.map((s) => <li key={s.season.id} className="flex justify-between p-3"><span>{s.season.name}</span><span className="text-muted-foreground">{s.matches} m · {s.runs} runs · {s.wickets} wkts</span></li>)}
          </ul>
        </section>
      )}

      <section aria-label="Match history" className="space-y-1">
        <h2 className="font-medium">Match history</h2>
        {d.history.length === 0 && <p className="text-sm text-muted-foreground">No matches yet.</p>}
        <ul className="space-y-2">
          {d.history.map((h) => (
            <li key={h.match_id}>
              <Link href={`/matches/${h.match_id}`} className="block rounded-lg border p-3 text-sm">
                <span className="font-medium">{h.round_label ?? `Match ${h.match_no}`}</span> vs {h.against}
                {h.won !== null && <span className={h.won ? " text-green-700" : " text-red-700"}> · {h.won ? "Won" : "Lost"}</span>}
                {h.potm && " ⭐"}
                <span className="block text-xs text-muted-foreground">
                  {h.batted ? `${h.runs} off ${h.balls}${h.out ? "" : "*"}` : "did not bat"}{h.bowled ? ` · ${h.wickets}/${h.runs_conceded} (${h.bowl_balls} balls)` : ""}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Player /></RequireAuth>;
}
