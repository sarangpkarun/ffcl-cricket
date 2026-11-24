"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api } from "@/lib/api";
import { KIND_LABEL, STATUS_LABEL, type DisputeRow, when } from "@/lib/disputes";

type Summary = { open: number; in_review: number; stale: number; mine: number };

function Queue() {
  const [f, setF] = useState({ status: "open", kind: "", assigned: "" });
  const [rows, setRows] = useState<DisputeRow[] | null>(null);
  const [sum, setSum] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now] = useState(() => Date.now()); // fixed when the page opens: "waiting over 3 days" does not need to tick
  const load = useCallback(async () => {
    const p = new URLSearchParams({ status: f.status });
    if (f.kind) p.set("kind", f.kind);
    if (f.assigned) p.set("assigned", f.assigned);
    try {
      const [r, s] = await Promise.all([api<DisputeRow[]>(`/admin/disputes?${p}`), api<Summary>("/admin/disputes/summary")]);
      setRows(r);
      setSum(s);
      setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, [f]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch when the filters change
  useEffect(() => { void load(); }, [load]);
  const stale = (d: DisputeRow) => d.status !== "resolved" && d.status !== "dismissed" && d.status !== "withdrawn" && now - new Date(d.created_at).getTime() > 72 * 3600_000;

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Disputes</h1>
      {sum && <p className="text-sm text-muted-foreground">{sum.open} waiting · {sum.in_review} being looked at · {sum.mine} yours{sum.stale > 0 && <b className="text-destructive"> · {sum.stale} waiting over 3 days</b>}</p>}
      <p className="text-xs text-muted-foreground">Disputes that involve your own team are not shown here: someone else decides those.</p>
      <div className="grid grid-cols-3 gap-2">
        <select aria-label="Status" className={inputCls} value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
          <option value="open">Open</option><option value="closed">Closed</option><option value="all">All</option>
        </select>
        <select aria-label="Kind" className={inputCls} value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="">Any kind</option>{Object.entries(KIND_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select aria-label="Assigned" className={inputCls} value={f.assigned} onChange={(e) => setF({ ...f, assigned: e.target.value })}>
          <option value="">Anyone</option><option value="me">Mine</option><option value="nobody">Nobody yet</option>
        </select>
      </div>
      <ErrorText msg={err} />
      {rows?.length === 0 && <p className="text-sm text-muted-foreground">Nothing here. 🎉</p>}
      <ul className="space-y-2">
        {rows?.map((d) => (
          <li key={d.id}>
            <Link href={`/disputes/${d.id}`} className={`block card-elevated rounded-2xl border bg-card p-3 text-sm ${stale(d) ? "border-destructive" : ""}`}>
              <p className="flex justify-between"><span className="font-medium">{KIND_LABEL[d.kind]}</span><span className="text-xs text-muted-foreground">{STATUS_LABEL[d.status]}{d.assigned_to ? ` · ${d.assigned_to}` : ""}</span></p>
              <p className="text-xs text-muted-foreground">{d.match ? `Match ${d.match.match_no}: ${d.match.teams}` : d.season.name} · {d.raised_by.name} · {when(d.created_at)}</p>
              <p className="mt-1">{d.excerpt}</p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Queue /></RequireAuth>;
}
