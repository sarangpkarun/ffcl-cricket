"use client";

import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season } from "@/lib/api";

type Version = { id: number; name: string; version: number; created_at: string; seasons: { id: number; name: string }[]; matches: number };
type Detail = { id: number; version: number; config: Record<string, unknown> & { points: Record<string, number>; stats: Record<string, number> }; previous: { id: number; version: number } | null; changes: { path: string; from: unknown; to: unknown }[] };

const FIELDS: { path: string; label: string }[] = [
  { path: "points.win", label: "Points for a win" },
  { path: "points.tie", label: "Points for a tie" },
  { path: "points.loss", label: "Points for a loss" },
  { path: "points.no_result", label: "Points each for no result" },
  { path: "points.walkover_win", label: "Points for a walkover win" },
  { path: "overs", label: "Overs" },
  { path: "wickets", label: "Wickets" },
  { path: "max_overs_per_bowler", label: "Overs per bowler" },
  { path: "umpire_duty_penalty", label: "Missed umpire duty penalty" },
  { path: "stats.min_balls_strike_rate", label: "Balls faced to qualify (strike rate)" },
  { path: "stats.min_balls_economy", label: "Balls bowled to qualify (economy)" },
];
const get = (o: unknown, path: string): unknown => path.split(".").reduce<unknown>((c, k) => (c as Record<string, unknown> | undefined)?.[k], o);
const nest = (path: string, v: number) => path.split(".").reduceRight<unknown>((acc, k) => ({ [k]: acc }), v) as Record<string, unknown>;
const merge = (a: Record<string, unknown>, b: Record<string, unknown>): Record<string, unknown> => {
  const out = { ...a };
  for (const [k, v] of Object.entries(b)) out[k] = typeof v === "object" && v && typeof out[k] === "object" ? merge(out[k] as Record<string, unknown>, v as Record<string, unknown>) : v;
  return out;
};

function Rules() {
  const [list, setList] = useState<Version[]>([]);
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [d, setD] = useState<Detail | null>(null);
  const [edit, setEdit] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [seasonId, setSeasonId] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [l, s] = await Promise.all([api<Version[]>("/admin/rules"), api<Season[]>("/seasons")]);
      setList(l);
      setSeasons(s);
      setSel((cur) => cur ?? l[0]?.id ?? null);
      setSeasonId((cur) => cur || String((s.find((x) => x.status === "active") ?? s[0])?.id ?? ""));
    } catch (e) { setErr((e as Error).message); }
  }, []);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    if (sel === null) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset the editor when another version is chosen
    setEdit({});
    api<Detail>(`/admin/rules/${sel}`).then(setD).catch((e) => setErr(e.message));
  }, [sel]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setErr(null); setOk(null);
    try { await fn(); setOk(done); await load(); } catch (e) { setErr((e as Error).message); }
  };
  const changes = FIELDS.filter((f) => edit[f.path] !== undefined && edit[f.path] !== "" && Number(edit[f.path]) !== get(d?.config, f.path))
    .reduce<Record<string, unknown>>((acc, f) => merge(acc, nest(f.path, Number(edit[f.path]))), {});

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-bold text-primary">Rule versions</h1>
      <ErrorText msg={err} />
      {ok && <p role="status" className="text-sm text-success">{ok}</p>}
      <select aria-label="Version" className={inputCls} value={sel ?? ""} onChange={(e) => setSel(Number(e.target.value))}>
        {list.map((v) => <option key={v.id} value={v.id}>{v.name} v{v.version} · {v.seasons.map((s) => s.name).join(", ") || "not in use"} · {v.matches} matches</option>)}
      </select>

      {d && (
        <>
          <section aria-label="Changes from the previous version" className="space-y-1 text-sm">
            <h2 className="font-medium">{d.previous ? `Changes from v${d.previous.version}` : "First version"}</h2>
            {d.previous && d.changes.length === 0 && <p className="text-muted-foreground">No differences.</p>}
            <ul>{d.changes.map((c) => <li key={c.path}><code>{c.path}</code>: {String(c.from)} → <b>{String(c.to)}</b></li>)}</ul>
          </section>

          <section aria-label="New version" className="space-y-2 card-elevated rounded-2xl border bg-card p-3">
            <h2 className="font-medium">New version from v{d.version}</h2>
            <div className="grid grid-cols-2 gap-2">
              {FIELDS.map((f) => (
                <Field key={f.path} label={f.label} type="number" min={0} placeholder={String(get(d.config, f.path))} value={edit[f.path] ?? ""} onChange={(e) => setEdit({ ...edit, [f.path]: e.target.value })} />
              ))}
            </div>
            <Field label="Why this change" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className={btnCls} disabled={Object.keys(changes).length === 0 || reason.length < 3}
              onClick={() => act(async () => { const r = await post<{ id: number }>("/admin/rules", { from_id: d.id, changes, reason }); setSel(r.id); setReason(""); }, "New version saved.")}>
              Save as a new version
            </button>
          </section>

          <section aria-label="Apply to a season" className="space-y-2 card-elevated rounded-2xl border bg-card p-3">
            <h2 className="font-medium">Use v{d.version} for a season</h2>
            <p className="text-xs text-muted-foreground">The table and matches that have not started switch over. Matches already under way or finished keep the version they started under.</p>
            <select aria-label="Season" className={inputCls} value={seasonId} onChange={(e) => setSeasonId(e.target.value)}>
              {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button className={btnGhost} onClick={() => act(async () => { const r = await post<{ repinned_matches: number }>(`/seasons/${seasonId}/rules`, { rule_set_id: d.id }); setOk(`Applied. ${r.repinned_matches} upcoming matches switched.`); }, "Applied.")}>Apply to this season</button>
          </section>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin global><Rules /></RequireAuth>;
}
