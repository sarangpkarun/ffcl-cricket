"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post, type Match, type Season, type Team } from "@/lib/api";

function SeasonPage() {
  const { id } = useParams<{ id: string }>();
  const [season, setSeason] = useState<Season | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [teamName, setTeamName] = useState("");
  const [color, setColor] = useState("#ff69b4");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [when, setWhen] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSeason(await api<Season>(`/seasons/${id}`));
      setTeams(await api<Team[]>(`/seasons/${id}/teams`));
      setMatches(await api<Match[]>(`/seasons/${id}/matches`));
    } catch (x) { setErr((x as Error).message); }
  }, [id]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void load(); }, [load]);

  const tname = (tid: number) => teams.find((t) => t.id === tid)?.name ?? `#${tid}`;
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); await load(); } catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">{season?.name ?? "Season"}</h1>
      <Link href={`/admin/seasons/${id}/setup`} className="block rounded-lg border p-3 text-center text-sm">📅 Generate and publish fixtures</Link>
      <ErrorText msg={err} />

      <section className="space-y-2">
        <h2 className="font-medium">Teams</h2>
        <ul className="space-y-2">
          {teams.map((t) => (
            <li key={t.id}>
              <Link href={`/teams/${t.id}`} className="flex items-center gap-2 rounded-lg border p-3">
                <span className="h-4 w-4 rounded-full" style={{ background: t.color ?? "#999" }} />
                {t.name}
              </Link>
            </li>
          ))}
        </ul>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void run(async () => { await post(`/seasons/${id}/teams`, { name: teamName, color }); setTeamName(""); }); }}>
          <Field label="Team name" required value={teamName} onChange={(e) => setTeamName(e.target.value)} />
          <label className="flex items-center gap-2 text-sm">Colour <input type="color" value={color} onChange={(e) => setColor(e.target.value)} /></label>
          <button className={btnCls}>Add team</button>
        </form>
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">Matches</h2>
        <ul className="space-y-2">
          {matches.map((m) => (
            <li key={m.id}>
              <Link href={`/matches/${m.id}`} className="block rounded-lg border p-3 text-sm">
                Match {m.match_no}: {tname(m.team_a_id)} vs {tname(m.team_b_id)} · {m.status}
              </Link>
            </li>
          ))}
        </ul>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void run(() => post(`/seasons/${id}/matches`, { team_a_id: Number(a), team_b_id: Number(b), scheduled_at: when ? new Date(when).toISOString() : null })); }}>
          <select className={inputCls} required value={a} onChange={(e) => setA(e.target.value)}>
            <option value="">Team A</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <select className={inputCls} required value={b} onChange={(e) => setB(e.target.value)}>
            <option value="">Team B</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <Field label="Date and time" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
          <button className={btnCls}>Create match</button>
        </form>
      </section>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><SeasonPage /></RequireAuth>;
}
