"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, type Bracket, type BracketMatch, type Season, type Standings } from "@/lib/api";

const TIEBREAK_LABEL: Record<string, string> = { points: "points", nrr: "net run rate", wins: "wins", head_to_head: "head-to-head", name: "name" };
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "Time to be confirmed";

function Form({ form }: { form: string[] }) {
  const tone: Record<string, string> = { W: "bg-green-600 text-white", L: "bg-red-600 text-white", T: "bg-amber-500 text-white", N: "bg-muted text-foreground" };
  return (
    <span className="flex gap-0.5" aria-label={`Form: ${form.join(" ")}`}>
      {form.map((f, i) => <span key={i} className={`inline-flex h-4 w-4 items-center justify-center rounded-sm text-[10px] ${tone[f] ?? ""}`}>{f}</span>)}
    </span>
  );
}

function Tie({ m }: { m: BracketMatch }) {
  const side = (t: BracketMatch["team_a"]) => (
    <span className={m.winner_team_id === t.id ? "font-semibold" : m.status === "completed" ? "text-muted-foreground" : ""}>
      {m.winner_team_id === t.id && "✓ "}{t.name}
    </span>
  );
  return (
    <Link href={`/matches/${m.id}`} className="block rounded-lg border p-3" aria-label={`${m.round_label}: ${m.team_a.name} vs ${m.team_b.name}`}>
      <p className="text-xs text-muted-foreground">{m.round_label} · #{m.match_no} · {m.status === "completed" ? "Final result" : when(m.scheduled_at)}</p>
      <p className="font-medium">{side(m.team_a)} <span className="text-muted-foreground">vs</span> {side(m.team_b)}</p>
      {m.result && <p className="text-sm">🏆 {m.result}</p>}
    </Link>
  );
}

function Table() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [seasonId, setSeasonId] = useState<number | null>(null);
  const [data, setData] = useState<Standings | null>(null);
  const [bracket, setBracket] = useState<Bracket | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((s) => {
      setSeasons(s);
      setSeasonId((s.find((x) => x.status === "active") ?? s[0])?.id ?? null);
    }).catch((e) => setErr(e.message));
  }, []);

  const load = useCallback(async () => {
    if (!seasonId) return;
    try {
      const [s, b] = await Promise.all([api<Standings>(`/seasons/${seasonId}/standings`), api<Bracket>(`/seasons/${seasonId}/bracket`)]);
      setData(s);
      setBracket(b);
      setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, [seasonId]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and when the season changes
    void load();
    const t = setInterval(() => void load(), 20_000);
    return () => clearInterval(t);
  }, [load]);

  const champion = bracket?.champion ?? data?.season.champion ?? null;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Points table</h1>
      {seasons.length > 1 && (
        <select aria-label="Season" className={inputCls} value={seasonId ?? ""} onChange={(e) => setSeasonId(Number(e.target.value))}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      )}
      <ErrorText msg={err} />
      {champion && <p role="status" className="rounded-lg bg-foreground px-4 py-3 text-center font-medium text-background">🏆 {champion.name} are champions</p>}

      {data && (
        <>
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm" aria-label="Points table">
              <thead className="text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-2 py-2">#</th><th className="py-2">Team</th>
                  <th className="px-1 text-right">P</th><th className="px-1 text-right">W</th><th className="px-1 text-right">L</th>
                  <th className="px-1 text-right">T</th><th className="px-1 text-right">Pts</th><th className="px-2 text-right">NRR</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={r.team.id} aria-label={`${r.position}. ${r.team.name}`}
                    className={`border-t ${r.qualified ? "border-l-4 border-l-green-600" : ""} ${i === data.qualifiers - 1 ? "border-b-2 border-b-foreground/30" : ""}`}>
                    <td className="px-2 py-2">{r.position}</td>
                    <td className="py-2">
                      <Link href={`/teams/${r.team.id}`} className="flex items-center gap-2 font-medium">
                        <span className="inline-block h-3 w-3 rounded-full" style={{ background: r.team.color ?? "#999" }} />{r.team.name}
                      </Link>
                      {r.form.length > 0 && <Form form={r.form} />}
                    </td>
                    <td className="px-1 text-right">{r.played}</td><td className="px-1 text-right">{r.won}</td>
                    <td className="px-1 text-right">{r.lost}</td><td className="px-1 text-right">{r.tied}</td>
                    <td className="px-1 text-right font-semibold">{r.points}{r.adjustments !== 0 && <sup title={`${r.adjustments > 0 ? "+" : ""}${r.adjustments} adjustment`}>*</sup>}</td>
                    <td className="px-2 text-right tabular-nums">{r.nrr > 0 ? "+" : ""}{r.nrr.toFixed(3)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-xs text-muted-foreground">
            Top {data.qualifiers} qualify. Win {data.points.win}, tie {data.points.tie}, loss {data.points.loss}.
            Level on points? {data.tiebreakers.filter((t) => t !== "points" && t !== "name").map((t) => TIEBREAK_LABEL[t] ?? t).join(", then ")}.
            {data.rows.some((r) => r.adjustments !== 0) && " * includes a points adjustment."}
          </p>
          {!data.league_complete && data.matches_counted > 0 && <p className="text-xs text-muted-foreground">{data.pending_matches.length} league match(es) still to play.</p>}
          {data.matches_counted === 0 && <p className="text-sm text-muted-foreground">No results yet. The table fills in as matches finish.</p>}
        </>
      )}

      {bracket?.stage && (
        <section className="space-y-2" aria-label="Knockouts">
          <h2 className="font-medium">Knockouts</h2>
          <ul className="space-y-2">{bracket.matches.map((m) => <li key={m.id}><Tie m={m} /></li>)}</ul>
        </section>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Table /></RequireAuth>;
}
