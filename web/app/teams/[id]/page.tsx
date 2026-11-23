"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { TeamAnalyticsBlock } from "@/components/league/AnalyticsBlocks";
import { UserSearch } from "@/components/UserSearch";
import { btnCls, btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, del, patch, post, type TeamDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type TeamStats = {
  table: { played: number; won: number; lost: number; tied: number; points: number; nrr: number; position: number } | null;
  win_pct: number | null;
  best: Record<string, { player: { id: number; name: string } | null; value: number; detail: string } | null>;
  players: { player: { id: number; name: string } | null; runs: number; wickets: number; matches: number }[];
};
const BEST = { most_runs: "Most runs", most_wickets: "Most wickets", highest_score: "Highest score" };

function StatsBlock({ id }: { id: string }) {
  const [s, setS] = useState<TeamStats | null>(null);
  useEffect(() => { api<TeamStats>(`/teams/${id}/stats`).then(setS).catch(() => {}); }, [id]);
  if (!s || !s.table || s.table.played === 0) return null;
  const t = s.table;
  return (
    <section aria-label="Team statistics" className="space-y-2 rounded-lg border p-3 text-sm">
      <h2 className="font-medium">Season statistics</h2>
      <p>#{t.position} · P{t.played} W{t.won} L{t.lost}{t.tied ? ` T${t.tied}` : ""} · {t.points} pts · NRR {t.nrr >= 0 ? "+" : ""}{t.nrr.toFixed(3)} · Win {s.win_pct}%</p>
      <ul className="space-y-1">
        {Object.entries(BEST).map(([k, label]) => { const b = s.best[k]; return b?.player && <li key={k}>{label}: <Link className="underline" href={`/players/${b.player.id}`}>{b.player.name}</Link> {b.value} <span className="text-xs text-muted-foreground">({b.detail})</span></li>; })}
      </ul>
    </section>
  );
}

type Change = { id: number; status: string; reason: string; decision_note: string | null; out: { id: number; name: string } | null; in: { id: number; name: string } | null };

function Replacements({ id, team, onDone }: { id: string; team: TeamDetail; onDone: () => void }) {
  const [rows, setRows] = useState<Change[]>([]);
  const [out, setOut] = useState("");
  const [inn, setInn] = useState<{ id: number; name: string } | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Change[]>(`/roster-changes?team_id=${id}`).then(setRows).catch(() => {}), [id]);
  useEffect(() => { void load(); }, [load]);
  const swappable = team.members.filter((m) => m.status === "approved" && m.user_id !== team.captain_id);
  return (
    <section aria-label="Replace a player" className="space-y-2 rounded-lg border p-3">
      <h2 className="font-medium">Replace a player</h2>
      <ErrorText msg={err} />
      <form className="space-y-2" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        try { await post(`/teams/${id}/roster-changes`, { out_user_id: Number(out), in_user_id: inn?.id, reason }); setOut(""); setInn(null); setReason(""); await load(); onDone(); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <select aria-label="Player leaving" className={inputCls} required value={out} onChange={(e) => setOut(e.target.value)}>
          <option value="">Player leaving</option>
          {swappable.map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
        </select>
        {inn ? <p className="text-sm">Joining: <b>{inn.name}</b> <button type="button" className="underline" onClick={() => setInn(null)}>change</button></p>
          : <UserSearch label="Search the player joining" onPick={(u) => setInn({ id: u.id, name: u.name })} />}
        <Field label="Reason" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} />
        <button className={btnCls} disabled={!inn}>Ask an admin to approve</button>
      </form>
      <ul className="space-y-1 text-sm">
        {rows.map((r) => (
          <li key={r.id} className="flex items-center justify-between gap-2 rounded border p-2">
            <span>{r.out?.name} → {r.in?.name} <span className="text-muted-foreground">· {r.status}{r.decision_note ? ` (${r.decision_note})` : ""}</span></span>
            {r.status === "pending" && <button className={btnGhost} onClick={async () => { await post(`/roster-changes/${r.id}/cancel`).catch(() => {}); await load(); }}>Cancel</button>}
          </li>
        ))}
      </ul>
    </section>
  );
}

function TeamPage() {
  const { id } = useParams<{ id: string }>();
  const { me, canAdmin } = useAuth();
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<TeamDetail>(`/teams/${id}`).then(setTeam).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { void load(); }, [load]);
  if (!team || !me) return <ErrorText msg={err} />;

  const isAdmin = canAdmin(team.season_id);
  const manager = isAdmin || team.captain_id === me.id;
  const mine = team.members.find((m) => m.user_id === me.id);
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); await load(); } catch (x) { setErr((x as Error).message); }
  };
  const approved = team.members.filter((m) => m.status === "approved").length;

  return (
    <div className="space-y-5">
      <h1 className="flex items-center gap-2 text-xl font-semibold">
        <span className="h-4 w-4 rounded-full" style={{ background: team.color ?? "#999" }} />
        {team.name}
      </h1>
      <p className="text-sm text-muted-foreground">{approved}/7 players</p>
      <ErrorText msg={err} />
      <StatsBlock id={id} />
      <TeamAnalyticsBlock teamId={id} />

      <ul className="space-y-2">
        {team.members.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
            <span>
              <Link href={`/players/${m.user_id}`} className="underline">{m.name}</Link> <span className="text-muted-foreground">{m.player_code}</span>
              {team.captain_id === m.user_id && " ©"}
              {m.status === "pending" && " (pending)"}
            </span>
            <span className="flex gap-2">
              {manager && m.status === "pending" && <button className={btnGhost} onClick={() => run(() => post(`/teams/${id}/members/${m.user_id}/approve`))}>Approve</button>}
              {isAdmin && m.status === "approved" && team.captain_id !== m.user_id && <button className={btnGhost} onClick={() => run(() => patch(`/teams/${id}`, { captain_id: m.user_id }))}>Captain</button>}
              {(manager || m.user_id === me.id) && <button className={btnGhost} onClick={() => run(() => del(`/teams/${id}/members/${m.user_id}`))}>Remove</button>}
            </span>
          </li>
        ))}
      </ul>

      {!mine && <button className={btnCls} onClick={() => run(() => post(`/teams/${id}/members`, {}))}>Request to join</button>}
      {manager && <Replacements id={id} team={team} onDone={() => void load()} />}
      {manager && <UserSearch label="Search player by name or ID to add" onPick={(u) => run(() => post(`/teams/${id}/members`, { user_id: u.id }))} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><TeamPage /></RequireAuth>;
}
