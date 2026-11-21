"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { UserSearch } from "@/components/UserSearch";
import { btnCls, btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, patch, post, put, type MatchDetail, type TeamDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function TeamLineup({ match, team, canEdit, onSaved }: { match: MatchDetail; team: TeamDetail; canEdit: boolean; onSaved: () => void }) {
  const current = match.lineup.filter((p) => p.team_id === team.id).map((p) => p.user_id);
  const [sel, setSel] = useState<number[]>(current);
  const [err, setErr] = useState<string | null>(null);
  const roster = team.members.filter((m) => m.status === "approved");
  const toggle = (uid: number) => setSel((s) => (s.includes(uid) ? s.filter((x) => x !== uid) : [...s, uid]));

  return (
    <section className="space-y-2 rounded-lg border p-3">
      <h2 className="font-medium">{team.name} ({sel.length}/7)</h2>
      <ul className="space-y-1">
        {roster.map((m) => (
          <li key={m.user_id}>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" disabled={!canEdit} checked={sel.includes(m.user_id)} onChange={() => toggle(m.user_id)} />
              {m.name} <span className="text-muted-foreground">{m.player_code}</span>
            </label>
          </li>
        ))}
      </ul>
      <ErrorText msg={err} />
      {canEdit && (
        <button className={btnCls} onClick={async () => {
          setErr(null);
          try { await put(`/matches/${match.id}/lineup`, { team_id: team.id, user_ids: sel }); onSaved(); }
          catch (x) { setErr((x as Error).message); }
        }}>Save lineup</button>
      )}
    </section>
  );
}

function MatchPage() {
  const { id } = useParams<{ id: string }>();
  const { me, isAdmin } = useAuth();
  const [match, setMatch] = useState<MatchDetail | null>(null);
  const [teams, setTeams] = useState<TeamDetail[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const m = await api<MatchDetail>(`/matches/${id}`);
      setMatch(m);
      setTeams(await Promise.all([m.team_a_id, m.team_b_id].map((t) => api<TeamDetail>(`/teams/${t}`))));
    } catch (x) { setErr((x as Error).message); }
  }, [id]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void load(); }, [load]);
  if (!match || !me) return <ErrorText msg={err} />;

  const [a, b] = teams;
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">Match {match.match_no}: {a?.name} vs {b?.name}</h1>
      <p className="text-sm text-muted-foreground">
        {match.scheduled_at ? new Date(match.scheduled_at).toLocaleString() : "Time TBD"} · {match.status}
        {match.umpire_id ? ` · umpire #${match.umpire_id}` : " · no umpire yet"}
      </p>
      <ErrorText msg={err} />
      {teams.map((t) => (
        <TeamLineup key={`${t.id}-${match.lineup.length}`} match={match} team={t}
          canEdit={match.status === "scheduled" && (isAdmin || t.captain_id === me.id)} onSaved={load} />
      ))}
      {isAdmin && match.status === "scheduled" && (
        <section className="space-y-2">
          <h2 className="font-medium">Assign umpire</h2>
          <UserSearch label="Search user to make umpire" onPick={async (u) => {
            setErr(null);
            try {
              await post(`/users/${u.id}/roles`, { role: "umpire" });
              await patch(`/matches/${id}`, { umpire_id: u.id });
              await load();
            } catch (x) { setErr((x as Error).message); }
          }} />
          <button className={btnGhost} onClick={async () => { await patch(`/matches/${id}`, { umpire_id: null }).catch(() => {}); await load(); }}>Clear umpire</button>
        </section>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><MatchPage /></RequireAuth>;
}
