"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, type Fixture, type Season, type Team } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Tab = "upcoming" | "live" | "completed";
const TABS: { key: Tab; label: string }[] = [
  { key: "upcoming", label: "Upcoming" },
  { key: "live", label: "Live" },
  { key: "completed", label: "Completed" },
];
const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "Time to be confirmed";

function Badge({ f }: { f: Fixture }) {
  const live = ["innings1", "break", "innings2"].includes(f.status);
  const text = !f.published ? "Draft" : f.paused ? "Paused" : live ? "● Live" : f.status === "completed" ? "Final" : f.status === "abandoned" ? "Abandoned" : f.status === "toss" ? "Toss" : "Scheduled";
  const tone = !f.published ? "border-amber-500 text-amber-700" : live ? "border-green-600 text-green-700" : "text-muted-foreground";
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{text}</span>;
}

function Card({ f }: { f: Fixture }) {
  const dot = (c: string | null) => <span className="inline-block h-3 w-3 rounded-full" style={{ background: c ?? "#999" }} />;
  return (
    <Link href={`/matches/${f.id}`} className="block space-y-1 rounded-lg border p-3" aria-label={`Match ${f.match_no}: ${f.team_a.name} vs ${f.team_b.name}`}>
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{f.round_label ?? "Match"} · #{f.match_no}</span>
        <Badge f={f} />
      </div>
      <p className="flex items-center gap-2 font-medium">
        {dot(f.team_a.color)} {f.team_a.name} <span className="text-muted-foreground">vs</span> {dot(f.team_b.color)} {f.team_b.name}
      </p>
      <p className="text-sm text-muted-foreground">{when(f.scheduled_at)}{f.umpire ? ` · umpire ${f.umpire}` : ""}</p>
      {f.result && <p className="text-sm font-medium">🏆 {f.result}</p>}
    </Link>
  );
}

function Fixtures() {
  const { isAdmin } = useAuth();
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
      setSeasonId((s.find((x) => x.status === "active") ?? s[0])?.id ?? null);
    }).catch((e) => setErr(e.message));
  }, []);
  useEffect(() => {
    if (seasonId) api<Team[]>(`/seasons/${seasonId}/teams`).then(setTeams).catch(() => setTeams([]));
  }, [seasonId]);

  const load = useCallback(async () => {
    if (!seasonId) return;
    const q = new URLSearchParams({ status: tab });
    if (teamId) q.set("team_id", teamId);
    if (drafts) q.set("include_drafts", "true");
    try { setRows(await api<Fixture[]>(`/seasons/${seasonId}/fixtures?${q}`)); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [seasonId, tab, teamId, drafts]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and when a filter changes
    void load();
    const t = setInterval(() => void load(), 15_000); // live matches change under you
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Fixtures</h1>
      {seasons.length > 1 && (
        <select aria-label="Season" className={inputCls} value={seasonId ?? ""} onChange={(e) => setSeasonId(Number(e.target.value))}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      )}
      <div role="tablist" className="flex rounded-lg border p-1">
        {TABS.map((t) => (
          <button key={t.key} role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
            className={`flex-1 rounded-md py-2 text-sm ${tab === t.key ? "bg-foreground text-background" : ""}`}>{t.label}</button>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <select aria-label="Team" className={inputCls} value={teamId} onChange={(e) => setTeamId(e.target.value)}>
          <option value="">All teams</option>
          {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
        {isAdmin && (
          <label className="flex items-center gap-2 whitespace-nowrap text-sm">
            <input type="checkbox" checked={drafts} onChange={(e) => setDrafts(e.target.checked)} /> Show drafts
          </label>
        )}
      </div>
      <ErrorText msg={err} />
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
