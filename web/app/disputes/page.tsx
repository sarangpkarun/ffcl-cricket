"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season, type Team } from "@/lib/api";
import { KIND_LABEL, STATUS_LABEL, type DisputeRow, when } from "@/lib/disputes";

function Complaint({ onDone }: { onDone: () => void }) {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [f, setF] = useState({ season: "", against: "", body: "" });
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => { api<Season[]>("/seasons").then((s) => { setSeasons(s); setF((c) => ({ ...c, season: String((s.find((x) => x.status === "active") ?? s[0])?.id ?? "") })); }).catch(() => {}); }, []);
  useEffect(() => { if (f.season) api<Team[]>(`/seasons/${f.season}/teams`).then(setTeams).catch(() => setTeams([])); }, [f.season]);
  return (
    <details className="rounded-lg border p-3">
      <summary className="cursor-pointer text-sm font-medium">Report a conduct problem</summary>
      <form className="mt-2 space-y-2" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        setOk(false);
        try { await post("/disputes", { kind: "conduct", body: f.body, season_id: Number(f.season), against_team_id: f.against ? Number(f.against) : null }); setF({ ...f, body: "" }); setOk(true); onDone(); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <select aria-label="Season" className={inputCls} value={f.season} onChange={(e) => setF({ ...f, season: e.target.value, against: "" })}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select aria-label="Team involved" className={inputCls} value={f.against} onChange={(e) => setF({ ...f, against: e.target.value })}>
          <option value="">No particular team</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        <textarea aria-label="What happened" className={inputCls} rows={4} required minLength={10} maxLength={2000} placeholder="What happened? Include the match and who was involved." value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
        <ErrorText msg={err} />
        {ok && <p role="status" className="text-sm text-green-700">Sent. The organisers will look at it.</p>}
        <button className={btnCls}>Send to the organisers</button>
      </form>
    </details>
  );
}

function MyDisputes() {
  const [rows, setRows] = useState<DisputeRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<DisputeRow[]>("/disputes").then(setRows).catch((e) => setErr(e.message)), []);
   
  useEffect(() => { void load(); }, [load]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Disputes</h1>
      <p className="text-sm text-muted-foreground">Disputes you raised, or that involve a team you captain. They are private: only the people involved and the organisers can see them.</p>
      <ErrorText msg={err} />
      {rows?.length === 0 && <p className="text-sm text-muted-foreground">Nothing here. To dispute a result, open the match after it finishes.</p>}
      <ul className="space-y-2">
        {rows?.map((d) => (
          <li key={d.id}>
            <Link href={`/disputes/${d.id}`} className="block rounded-lg border p-3 text-sm">
              <p className="flex justify-between"><span className="font-medium">{KIND_LABEL[d.kind]}</span><span className="text-xs text-muted-foreground">{STATUS_LABEL[d.status]}</span></p>
              <p className="text-xs text-muted-foreground">{d.match ? `Match ${d.match.match_no}: ${d.match.teams}` : d.season.name} · {d.raised_by.name} · {when(d.updated_at)}</p>
              <p className="mt-1">{d.excerpt}</p>
            </Link>
          </li>
        ))}
      </ul>
      <Complaint onDone={() => void load()} />
    </div>
  );
}

export default function Page() {
  return <RequireAuth><MyDisputes /></RequireAuth>;
}
