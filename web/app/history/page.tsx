"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ErrorText, RequireAuth } from "@/components/ui-bits";
import { api } from "@/lib/api";

type Lead = { player: { id: number; name: string }; value: number; detail: string } | null;
type Past = {
  season: { id: number; name: string; status: string };
  champion: { id: number; name: string } | null;
  table: { position: number; team: string; played: number; won: number; lost: number; points: number; nrr: number }[];
  top_batter: Lead; top_bowler: Lead; most_awards: Lead; matches: number; teams: number;
};

function History() {
  const [rows, setRows] = useState<Past[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Past[]>("/history").then(setRows).catch((e) => setErr(e.message)); }, []);
  const lead = (label: string, l: Lead, unit: string) => l && <li>{label}: <Link className="underline" href={`/players/${l.player.id}`}>{l.player.name}</Link> {l.value} {unit}</li>;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Season history</h1>
      <ErrorText msg={err} />
      {rows?.length === 0 && <p className="text-sm text-muted-foreground">No finished seasons yet.</p>}
      {rows?.map((s) => (
        <section key={s.season.id} aria-label={s.season.name} className="space-y-2 rounded-lg border p-3 text-sm">
          <h2 className="font-medium">{s.season.name} <span className="text-xs text-muted-foreground">{s.teams} teams · {s.matches} matches</span></h2>
          {s.champion && <p className="font-medium">🏆 Champions: {s.champion.name}</p>}
          <ol className="divide-y rounded border">
            {s.table.map((r) => (
              <li key={r.position} className="flex justify-between p-2"><span>{r.position}. {r.team}</span><span className="text-muted-foreground">P{r.played} W{r.won} L{r.lost} · {r.points} pts · {r.nrr >= 0 ? "+" : ""}{r.nrr.toFixed(3)}</span></li>
            ))}
          </ol>
          <ul className="space-y-0.5">
            {lead("Most runs", s.top_batter, "")}
            {lead("Most wickets", s.top_bowler, "")}
            {lead("Most player of the match awards", s.most_awards, "")}
          </ul>
        </section>
      ))}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><History /></RequireAuth>;
}
