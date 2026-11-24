"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { chooseSeason, rememberSeason } from "@/lib/seasons";
import { api, type Fixture, type Season, type Team } from "@/lib/api";
import { FixtureCard as Card } from "@/components/FixtureCard";
import { useAuth } from "@/lib/auth";
import { ListSkeleton } from "@/components/Skeleton";

type Tab = "upcoming" | "live" | "completed";
const TABS: { key: Tab; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "live", label: "Live" },
  { key: "completed", label: "Completed" },
];
function Fixtures() {
  const { canAdmin } = useAuth();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [seasonId, setSeasonId] = useState<number | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [teamId, setTeamId] = useState("");
  const [drafts, setDrafts] = useState(false);
  const [rows, setRows] = useState<Fixture[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((s) => {
      setSeasons(s);
      setSeasonId(chooseSeason(s)?.id ?? null);
    }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    if (seasonId) api<Team[]>(`/seasons/${seasonId}/teams`).then(setTeams).catch(() => setTeams([]));
  }, [seasonId]);

  const load = useCallback(async (current: () => boolean = () => true) => {
    if (!seasonId) return;
    const q = new URLSearchParams({ status: tab });
    if (teamId) q.set("team_id", teamId);
    if (drafts) q.set("include_drafts", "true");
    try { const r = await api<Fixture[]>(`/seasons/${seasonId}/fixtures?${q}`); if (current()) { setRows(r); setErr(null); } } catch (e) { setErr((e as Error).message); }
  }, [seasonId, tab, teamId, drafts]);
  useEffect(() => {
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and when the season or a filter changes
    void load(() => live);
    const t = setInterval(() => void load(() => live), 15_000); // live matches change under you
    return () => { live = false; clearInterval(t); };
  }, [load]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Fixtures</h1>
      {seasons.length > 1 && (
        <select aria-label="Season" className={inputCls} value={seasonId ?? ""} onChange={(e) => { rememberSeason(e.target.value); setSeasonId(Number(e.target.value)); }}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      )}
      <div role="tablist" className="flex rounded-2xl border bg-muted p-1">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`flex-1 rounded-xl py-2 text-sm font-medium transition ${tab === t.key ? "bg-primary text-primary-foreground shadow" : "text-muted-foreground"}`}>{t.label}</button>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <select aria-label="Team" className={inputCls} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        {canAdmin(seasonId) && (
          <label className="flex items-center gap-2 whitespace-nowrap text-sm">
            <input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} /> Show drafts
          </label>
        )}
      </div>
      <ErrorText msg={err} />
      {rows === null && !err && <ListSkeleton rows={2} />}
      {rows && rows.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {tab === "upcoming" ? "No upcoming matches yet. Fixtures appear here once the organisers publish them." : tab === "live" ? "No match is being played right now." : "No completed matches yet."}
        </p>
      )}
      <ul className="space-y-2">
        {rows?.map((f) => <li key={f.id}><Card f={f} /></li>)}
      </ul>
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Fixtures /></RequireAuth>;
}
