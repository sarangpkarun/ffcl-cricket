"use client";

import { useCallback, useEffect, useState } from "react";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { Tie } from "@/components/league/Bracket";
import { StandingsTable } from "@/components/league/StandingsTable";
import { chooseSeason, rememberSeason } from "@/lib/seasons";
import { api, type Bracket, type Season, type Standings } from "@/lib/api";


function Table() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [seasonId, setSeasonId] = useState<number | null>(null);
  const [data, setData] = useState<Standings | null>(null);
  const [bracket, setBracket] = useState<Bracket | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Season[]>("/seasons").then((s) => {
      setSeasons(s);
      setSeasonId(chooseSeason(s)?.id ?? null);
    }).catch((e) => setErr(e.message));
  }, []);

  // `current` says whether the answer is still wanted: a slow reply for a season you have since left must not overwrite the newer one
  const load = useCallback(async (current: () => boolean = () => true) => {
    if (!seasonId) return;
    try {
      const [s, b] = await Promise.all([api<Standings>(`/seasons/${seasonId}/standings`), api<Bracket>(`/seasons/${seasonId}/bracket`)]);
      if (!current()) return;
      setData(s);
      setBracket(b);
      setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, [seasonId]);
  useEffect(() => {
    let live = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount and when the season or a filter changes
    void load(() => live);
    const t = setInterval(() => void load(() => live), 20_000);
    return () => { live = false; clearInterval(t); };
  }, [load]);

  const champion = bracket?.champion ?? data?.season.champion ?? null;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Points table</h1>
      {seasons.length > 1 && (
        <select aria-label="Season" className={inputCls} value={seasonId ?? ""} onChange={(e) => { rememberSeason(e.target.value); setSeasonId(Number(e.target.value)); }}>
          {seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      )}
      <ErrorText msg={err} />
      {champion && <p role="status" className="rounded-lg bg-foreground px-4 py-3 text-center font-medium text-background">🏆 {champion.name} are champions</p>}

      {data && (
        <>
          <StandingsTable data={data} teamHref={(id) => `/teams/${id}`} />
        </>
      )}

      {bracket?.stage && (
        <section className="space-y-2" aria-label="Knockouts">
          <h2 className="font-medium">Knockouts</h2>
          <ul className="space-y-2">{bracket.matches.map((m) => <li key={m.id}><Tie m={m} href={`/matches/${m.id}`} /></li>)}</ul>
        </section>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Table /></RequireAuth>;
}
