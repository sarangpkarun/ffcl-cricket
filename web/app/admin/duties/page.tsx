"use client";

import { useCallback, useEffect, useState } from "react";
import { btnGhost, ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { adminSeasons, chooseSeason, rememberSeason } from "@/lib/seasons";
import { useAuth } from "@/lib/auth";
import { api, post, type Season } from "@/lib/api";

type Duty = {
  id: number; status: string; note: string | null;
  umpire: { id: number; name: string | null }; team: { id: number; name: string | null } | null;
  match: { id: number; match_no: number; teams: string; scheduled_at: string | null };
};

function Duties() {
  const { adminScope } = useAuth();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [rows, setRows] = useState<Duty[]>([]);
  const [why, setWhy] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((all) => { const s = adminSeasons(all, adminScope); setSeasons(s); setSid(String(chooseSeason(s)?.id ?? "")); }).catch((e) => setErr(e.message));
  }, [adminScope]);
  const load = useCallback(async (current: () => boolean = () => true) => {
    if (!sid) return;
    try { const r = await api<Duty[]>(`/seasons/${sid}/duties`); if (current()) setRows(r); } catch (e) { setErr((e as Error).message); }
  }, [sid]);
   
  useEffect(() => {
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and when the season or a filter changes
    void load(() => live);
    return () => { live = false; };
  }, [load]);

  const act = async (d: Duty, what: "missed" | "reverse") => {
    setErr(null);
    try { await post(`/duties/${d.id}/${what}`, { reason: why[d.id] ?? "" }); await load(); } catch (x) { setErr((x as Error).message); }
  };

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Umpire duties</h1>
      <select aria-label="Season" className={inputCls} value={sid} onChange={(e) => { rememberSeason(e.target.value); setSid(e.target.value); }}>
        {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
      <ErrorText msg={err} />
      <ul className="space-y-2">
        {rows.length === 0 && <li className="text-sm text-muted-foreground">No duties yet.</li>}
        {rows.map((d) => (
          <li key={d.id} className="space-y-2 rounded-lg border p-3 text-sm">
            <p><strong>Match {d.match.match_no}</strong> · {d.match.teams}<br />
              <span className="text-xs text-muted-foreground">{d.umpire.name}{d.team ? ` (for ${d.team.name})` : ""} · {d.status}{d.note ? ` · ${d.note}` : ""}</span></p>
            {(d.status === "assigned" || d.status === "missed") && (
              <div className="flex gap-2">
                <input aria-label={`Reason for duty ${d.id}`} placeholder="Reason" className="min-w-0 flex-1 rounded border bg-background px-2 py-2" value={why[d.id] ?? ""} onChange={(e) => setWhy({ ...why, [d.id]: e.target.value })} />
                {d.status === "assigned"
                  ? <button className={btnGhost} onClick={() => act(d, "missed")}>Mark missed</button>
                  : <button className={btnGhost} onClick={() => act(d, "reverse")}>Reverse</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Duties /></RequireAuth>;
}
