"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, Field, RequireAuth } from "@/components/ui-bits";
import { api, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Dash = {
  season: { id: number; name: string; slug: string; status: string; is_public: boolean; champion: string | null };
  rules: { id: number; name: string; version: number } | null;
  teams: number; players: number; adjustments: number;
  matches: { drafts: number; upcoming: number; live: number; finished: number };
  next: { id: number; match_no: number; teams: string; scheduled_at: string | null }[];
  waiting: { roster_changes: number; disputes: number; missed_duties: number };
};

function Stat({ label, value, href }: { label: string; value: number | string; href?: string }) {
  const body = <><p className="text-lg font-semibold">{value}</p><p className="text-xs text-muted-foreground">{label}</p></>;
  return href ? <Link href={href} className="rounded-lg border p-2 text-center">{body}</Link> : <div className="rounded-lg border p-2 text-center">{body}</div>;
}

function Clone({ d, onDone }: { d: Dash; onDone: (id: number) => void }) {
  const [name, setName] = useState("");
  const [teams, setTeams] = useState(true);
  const [rosters, setRosters] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <details className="rounded-lg border p-3">
      <summary className="cursor-pointer text-sm font-medium">Start the next season from this one</summary>
      <form className="mt-2 space-y-2" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        try { const r = await post<{ id: number }>(`/seasons/${d.season.id}/clone`, { name, copy_teams: teams || rosters, copy_rosters: rosters }); onDone(r.id); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <p className="text-xs text-muted-foreground">It starts as a hidden draft with the same rule version. Matches, results and points are never copied.</p>
        <Field label="Name of the new season" required value={name} onChange={(e) => setName(e.target.value)} />
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={teams || rosters} disabled={rosters} onChange={(e) => setTeams(e.target.checked)} /> Copy the teams</label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={rosters} onChange={(e) => setRosters(e.target.checked)} /> Also copy the players, captains and vice-captains</label>
        <ErrorText msg={err} />
        <button className={btnCls}>Create the new season</button>
      </form>
    </details>
  );
}

function Dashboard() {
  const { id } = useParams<{ id: string }>();
  const { isGlobalAdmin } = useAuth();
  const [d, setD] = useState<Dash | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [made, setMade] = useState<number | null>(null);
  const load = useCallback(() => api<Dash>(`/admin/seasons/${id}/dashboard`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message)), [id]);
   
  useEffect(() => { void load(); }, [load]);
  if (!d) return <ErrorText msg={err} />;
  const w = d.waiting;
  return (
    <div className="space-y-5">
      <header>
        <p className="text-xs text-muted-foreground">{d.season.status}{d.season.is_public ? "" : " · hidden from the public"}{d.rules ? ` · rules ${d.rules.name} v${d.rules.version}` : ""}</p>
        <h1 className="text-xl font-semibold">{d.season.name}</h1>
        {d.season.champion && <p className="text-sm">🏆 {d.season.champion}</p>}
      </header>
      <section aria-label="At a glance" className="grid grid-cols-3 gap-2">
        <Stat label="Teams" value={d.teams} /><Stat label="Players" value={d.players} /><Stat label="Point adjustments" value={d.adjustments} href="/admin/adjustments" />
        <Stat label="Draft matches" value={d.matches.drafts} href={`/admin/seasons/${id}/setup`} /><Stat label="Upcoming" value={d.matches.upcoming} /><Stat label="Live" value={d.matches.live} />
      </section>
      <section aria-label="Waiting for you" className="space-y-1">
        <h2 className="font-medium">Waiting for you</h2>
        <ul className="space-y-1 text-sm">
          <li><Link className="underline" href="/admin/approvals">Roster changes</Link>: {w.roster_changes}</li>
          <li><Link className="underline" href="/admin/disputes">Disputes</Link>: {w.disputes}</li>
          <li><Link className="underline" href="/admin/duties">Umpire duties recorded as missed</Link>: {w.missed_duties}</li>
        </ul>
      </section>
      {d.next.length > 0 && (
        <section aria-label="Next matches" className="space-y-1">
          <h2 className="font-medium">Next matches</h2>
          <ul className="space-y-1 text-sm">{d.next.map((m) => <li key={m.id}><Link className="underline" href={`/matches/${m.id}`}>Match {m.match_no}: {m.teams}</Link></li>)}</ul>
        </section>
      )}
      <nav aria-label="Manage this season" className="flex flex-wrap gap-3 text-sm">
        <Link className="underline" href={`/admin/seasons/${id}/setup`}>Fixtures, knockouts, archive and exports</Link>
        <Link className="underline" href={`/seasons/${id}`}>Teams</Link>
        <Link className="underline" href="/insights">Insights</Link>
        <Link className="underline" href={`/league/${d.season.slug}`}>Public page</Link>
      </nav>
      {made && <p role="status" className="rounded-lg bg-muted p-3 text-sm">New season created. <Link className="underline" href={`/admin/seasons/${made}`}>Open it</Link></p>}
      {isGlobalAdmin && <Clone d={d} onDone={setMade} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Dashboard /></RequireAuth>;
}
