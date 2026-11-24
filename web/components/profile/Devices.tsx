"use client";

import { useCallback, useEffect, useState } from "react";
import { btnGhost, ErrorText } from "@/components/ui-bits";
import { api, del } from "@/lib/api";

type Row = { id: number; device: string; last_active: string; current: boolean };

/** Where this account is signed in, with a way to end any sign-in but this one. */
export function Devices() {
  const [rows, setRows] = useState<Row[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Row[]>("/me/sessions").then((r) => { setRows(r); setErr(null); }).catch((e) => setErr(e.message)), []);
  useEffect(() => { void load(); }, [load]);
  return (
    <section aria-label="Where you are signed in" className="space-y-2 card-elevated rounded-2xl border bg-card p-4">
      <h2 className="font-medium">Where you are signed in</h2>
      <ErrorText msg={err} />
      <ul className="space-y-2 text-sm">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 rounded border p-2">
            <span className="min-w-0">
              <span className="block truncate">{r.device}</span>
              <span className="text-xs text-muted-foreground">{r.current ? "This device · " : ""}last active {new Date(r.last_active).toLocaleString()}</span>
            </span>
            {!r.current && <button className={btnGhost} aria-label={`Sign out ${r.device}`} onClick={async () => { try { await del(`/me/sessions/${r.id}`); await load(); } catch (e) { setErr((e as Error).message); } }}>Sign out</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}
