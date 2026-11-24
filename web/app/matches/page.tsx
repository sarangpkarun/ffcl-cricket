"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { RequireAuth } from "@/components/ui-bits";
import { api, type Match, type Season, type Team } from "@/lib/api";

function Matches() {
  const [rows, setRows] = useState<{ m: Match; names: Record<number, string> }[]>([]);
  const [msg, setMsg] = useState("Loading…");
  useEffect(() => {
    (async () => {
      const seasons = await api<Season[]>("/seasons");
      const season = seasons.find((s) => s.status === "active") ?? seasons[0];
      if (!season) return setMsg("No season yet.");
      const [teams, matches] = await Promise.all([
        api<Team[]>(`/seasons/${season.id}/teams`),
        api<Match[]>(`/seasons/${season.id}/matches`),
      ]);
      const names = Object.fromEntries(teams.map((t) => [t.id, t.name]));
      setRows(matches.map((m) => ({ m, names })));
      setMsg(matches.length ? "" : "No matches scheduled yet.");
    })().catch((e) => setMsg(e.message));
  }, []);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Matches</h1>
      {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
      <ul className="space-y-2">
        {rows.map(({ m, names }) => (
          <li key={m.id}>
            <Link href={`/matches/${m.id}`} className="card-elevated block rounded-2xl border bg-card p-4">
              <p className="font-medium">Match {m.match_no}: {names[m.team_a_id]} vs {names[m.team_b_id]}</p>
              <p className="text-sm text-muted-foreground">
                {m.scheduled_at ? new Date(m.scheduled_at).toLocaleString() : "Time TBD"} · {m.status}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Matches /></RequireAuth>;
}
