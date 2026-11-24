"use client";

import { useCallback, useEffect, useState } from "react";
import { btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api } from "@/lib/api";

type Entry = { id: number; at: string; actor: { id: number; name: string | null } | null; action: string; entity: string; entity_id: number | null; reason: string | null; before: unknown; after: unknown };
type Page = { entries: Entry[]; next_before_id: number | null };

function Audit() {
  const [actions, setActions] = useState<string[]>([]);
  const [f, setF] = useState({ action: "", entity: "", entity_id: "", actor_id: "", q: "", since: "", until: "" });
  const [rows, setRows] = useState<Entry[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const query = useCallback((before?: number) => {
    const p = new URLSearchParams({ limit: "30" });
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, k === "since" || k === "until" ? new Date(v).toISOString() : v);
    if (before) p.set("before_id", String(before));
    return api<Page>(`/admin/audit?${p}`);
  }, [f]);
  const search = useCallback(async () => {
    try { const r = await query(); setRows(r.entries); setNext(r.next_before_id); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [query]);
  useEffect(() => { api<string[]>("/admin/audit/actions").then(setActions).catch(() => {}); }, []);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- first load
  useEffect(() => { void search(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Audit log</h1>
      <form className="grid grid-cols-2 gap-2" onSubmit={(e) => { e.preventDefault(); void search(); }}>
        <select aria-label="Action" className={inputCls} value={f.action} onChange={(e) => setF({ ...f, action: e.target.value })}>
          <option value="">Any action</option>
          {actions.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <Field label="Person ID" inputMode="numeric" value={f.actor_id} onChange={(e) => setF({ ...f, actor_id: e.target.value })} />
        <Field label="Record type (e.g. match)" value={f.entity} onChange={(e) => setF({ ...f, entity: e.target.value })} />
        <Field label="Record ID" inputMode="numeric" value={f.entity_id} onChange={(e) => setF({ ...f, entity_id: e.target.value })} />
        <Field label="From" type="datetime-local" value={f.since} onChange={(e) => setF({ ...f, since: e.target.value })} />
        <Field label="Until" type="datetime-local" value={f.until} onChange={(e) => setF({ ...f, until: e.target.value })} />
        <div className="col-span-2"><Field label="Text in the reason" value={f.q} onChange={(e) => setF({ ...f, q: e.target.value })} /></div>
        <button className={`${btnGhost} col-span-2`}>Search</button>
      </form>
      <ErrorText msg={err} />
      <ul className="space-y-2">
        {rows.length === 0 && <li className="text-sm text-muted-foreground">No entries.</li>}
        {rows.map((e) => (
          <li key={e.id} className="card-elevated rounded-2xl border bg-card p-3 text-sm">
            <p><b>{e.action}</b> <span className="text-muted-foreground">{e.entity}{e.entity_id ? ` #${e.entity_id}` : ""}</span></p>
            <p className="text-xs text-muted-foreground">{new Date(e.at).toLocaleString()} · {e.actor?.name ?? "system"}{e.reason ? ` · ${e.reason}` : ""}</p>
            {Boolean(e.before || e.after) && <details className="text-xs"><summary className="cursor-pointer">Details</summary><pre className="overflow-x-auto whitespace-pre-wrap break-words">{JSON.stringify({ before: e.before, after: e.after }, null, 1)}</pre></details>}
          </li>
        ))}
      </ul>
      {next && <button className={btnGhost} onClick={async () => { try { const r = await query(next); setRows([...rows, ...r.entries]); setNext(r.next_before_id); } catch (e) { setErr((e as Error).message); } }}>Load older entries</button>}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin global><Audit /></RequireAuth>;
}
