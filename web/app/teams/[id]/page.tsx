"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { UserSearch } from "@/components/UserSearch";
import { btnCls, btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, del, patch, post, type TeamDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function TeamPage() {
  const { id } = useParams<{ id: string }>();
  const { me, isAdmin } = useAuth();
  const [team, setTeam] = useState<TeamDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<TeamDetail>(`/teams/${id}`).then(setTeam).catch((e) => setErr(e.message)), [id]);
  useEffect(() => { void load(); }, [load]);
  if (!team || !me) return <ErrorText msg={err} />;

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

      <ul className="space-y-2">
        {team.members.map((m) => (
          <li key={m.user_id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
            <span>
              {m.name} <span className="text-muted-foreground">{m.player_code}</span>
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
      {manager && <UserSearch label="Search player by name or ID to add" onPick={(u) => run(() => post(`/teams/${id}/members`, { user_id: u.id }))} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><TeamPage /></RequireAuth>;
}
