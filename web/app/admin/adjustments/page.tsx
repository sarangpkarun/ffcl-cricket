"use client";

import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season, type Team } from "@/lib/api";

type Adj = { id: number; team: { id: number; name: string | null }; points: number; kind: string; reason: string; created_by: string | null; voided: boolean };

function Adjustments() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [teams, setTeams] = useState<Team[]>([]);
  const [rows, setRows] = useState<Adj[]>([]);
  const [form, setForm] = useState({ team: "", points: "", reason: "" });
  const [voidWhy, setVoidWhy] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((s) => { setSeasons(s); setSid(String((s.find((x) => x.status === "active") ?? s[0])?.id ?? "")); }).catch((e) => setErr(e.message));
  }, []);
  const load = useCallback(async () => {
    if (!sid) return;
    try {
      const [t, a] = await Promise.all([api<Team[]>(`/seasons/${sid}/teams`), api<Adj[]>(`/seasons/${sid}/adjustments?include_voided=true`)]);
      setTeams(t);
      setRows(a);
    } catch (e) { setErr((e as Error).message); }
  }, [sid]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch when the season changes
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Points adjustments</h1>
      <select aria-label="Season" className={inputCls} value={sid} onChange={(e) => setSid(e.target.value)}>
        {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <ErrorText msg={err} />
      <form className="space-y-2 rounded-lg border p-3" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        try { await post(`/seasons/${sid}/adjustments`, { team_id: Number(form.team), points: Number(form.points), reason: form.reason, kind: "manual" }); setForm({ team: "", points: "", reason: "" }); await load(); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <select aria-label="Team" className={inputCls} required value={form.team} onChange={(e) => setForm({ ...form, team: e.target.value })}>
          <option value="">Team</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <Field label="Points (+/-)" type="number" required value={form.points} onChange={(e) => setForm({ ...form, points: e.target.value })} />
        <Field label="Reason" required minLength={3} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <button className={btnCls}>Add adjustment</button>
      </form>
      <ul className="space-y-2">
        {rows.length === 0 && <li className="text-sm text-muted-foreground">No adjustments yet.</li>}
        {rows.map((a) => (
          <li key={a.id} className="space-y-2 rounded-lg border p-3 text-sm">
            <p className={a.voided ? "line-through opacity-60" : ""}><strong>{a.team.name}</strong> {a.points > 0 ? "+" : ""}{a.points} · {a.kind.replace("_", " ")}<br /><span className="text-xs text-muted-foreground">{a.reason} · {a.created_by}</span></p>
            {a.voided ? <p className="text-xs text-muted-foreground">Cancelled</p> : (
              <div className="flex gap-2">
                <input aria-label={`Reason to cancel adjustment ${a.id}`} placeholder="Reason to cancel" className="min-w-0 flex-1 rounded border bg-background px-2 py-2" value={voidWhy[a.id] ?? ""} onChange={(e) => setVoidWhy({ ...voidWhy, [a.id]: e.target.value })} />
                <button className={btnGhost} onClick={async () => {
                  setErr(null);
                  try { await post(`/adjustments/${a.id}/void`, { reason: voidWhy[a.id] ?? "" }); await load(); } catch (x) { setErr((x as Error).message); }
                }}>Cancel</button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Adjustments /></RequireAuth>;
}
