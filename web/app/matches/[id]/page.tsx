"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { PlayerPanel } from "@/components/match/PlayerPanel";
import { Scoreboard } from "@/components/match/Scoreboard";
import { TossPanel } from "@/components/match/TossPanel";
import { UmpireConsole } from "@/components/match/UmpireConsole";
import { UserSearch } from "@/components/UserSearch";
import { btnCls, btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, patch, post, put, type MatchDetail, type TeamDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useLive } from "@/lib/useLive";

function TeamLineup({ match, team, canEdit, onSaved }: { match: MatchDetail; team: TeamDetail; canEdit: boolean; onSaved: () => void }) {
  const current = match.lineup.filter((p) => p.team_id === team.id).map((p) => p.user_id);
  const [sel, setSel] = useState<number[]>(current);
  const [err, setErr] = useState<string | null>(null);
  const roster = team.members.filter((m) => m.status === "approved");
  const toggle = (uid: number) => setSel((s) => (s.includes(uid) ? s.filter((x) => x !== uid) : [...s, uid]));

  return (
    <section className="space-y-2 rounded-lg border p-3">
      <h2 className="font-medium">{team.name} ({canEdit ? sel.length : current.length}/7)</h2>
      <ul className="space-y-1">
        {roster.map((m) => (
          <li key={m.user_id}>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" disabled={!canEdit} checked={(canEdit ? sel : current).includes(m.user_id)} onChange={() => toggle(m.user_id)} />
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
  const { live, error, refresh } = useLive(id);
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
  if (!match || !me || !live) return <ErrorText msg={err ?? error} />;

  const done = () => { void refresh(); void load(); };
  const official = live.you.official;
  const myTeamIds = teams.filter((t) => t.captain_id === me.id).map((t) => t.id);
  const lineups = Object.fromEntries(teams.map((t) => [
    t.id,
    match.lineup.filter((p) => p.team_id === t.id).map((p) => ({ id: p.user_id, name: t.members.find((m) => m.user_id === p.user_id)?.name ?? null })),
  ]));
  const active = live.innings.find((i) => i.status === "active");
  const battingName = active ? live.match.teams[String(active.batting_team_id)] : "";

  return (
    <div className="space-y-5">
      <Scoreboard live={live} />
      <ErrorText msg={err ?? error} />
      {live.over && live.over.your_role && live.over.state !== "resolved" && (
        <PlayerPanel matchId={match.id} over={live.over} battingTeam={battingName} onDone={done} />
      )}
      <TossPanel live={live} myTeamIds={myTeamIds} onDone={done} />
      {official && <UmpireConsole live={live} lineups={lineups} onDone={done} />}

      {live.match.status === "scheduled" && (
        <div className="space-y-3">
          <h2 className="font-medium">Lineups</h2>
          {teams.map((t) => (
            <TeamLineup key={`${t.id}-${match.lineup.length}`} match={match} team={t} canEdit={isAdmin || t.captain_id === me.id} onSaved={load} />
          ))}
        </div>
      )}
      {isAdmin && live.match.status === "scheduled" && (
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
