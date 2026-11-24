"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { BarChart3, CalendarDays, Table2 } from "lucide-react";
import { ListSkeleton } from "@/components/Skeleton";
import { FixtureCard } from "@/components/FixtureCard";
import { api, type Fixture, type Season } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { chooseSeason } from "@/lib/seasons";

const tile = "card-elevated flex flex-col items-center gap-1.5 rounded-2xl border bg-card p-3 text-center text-sm font-medium text-primary transition active:scale-[0.98]";

/** The signed-in home screen: what is being played now and what is next, in the season you last looked at. */
export function Dashboard() {
  const { me, isAdmin } = useAuth();
  const [season, setSeason] = useState<Season | null | undefined>(undefined); // undefined = still loading
  const [live, setLive] = useState<Fixture[]>([]);
  const [next, setNext] = useState<Fixture[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let on = true;
    api<Season[]>("/seasons").then((all) => { if (on) setSeason(chooseSeason(all) ?? null); }).catch((e) => { if (on) { setSeason(null); setErr(e.message); } });
    return () => { on = false; };
  }, []);

  const load = useCallback(async (current: () => boolean) => {
    if (!season) return;
    try {
      const [l, u] = await Promise.all([
        api<Fixture[]>(`/seasons/${season.id}/fixtures?status=live`),
        api<Fixture[]>(`/seasons/${season.id}/fixtures?status=upcoming`),
      ]);
      if (current()) { setLive(l); setNext(u.slice(0, 3)); setErr(null); }
    } catch (e) { if (current()) setErr((e as Error).message); }
  }, [season]);
  useEffect(() => {
    let on = true;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch when the season is known, then keep live matches fresh
    void load(() => on);
    const t = setInterval(() => void load(() => on), 15_000);
    return () => { on = false; clearInterval(t); };
  }, [load]);

  if (season === undefined) return <ListSkeleton />;
  if (season === null) {
    return (
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Welcome{me ? `, ${me.name}` : ""}</h1>
        {isAdmin
          ? <p className="text-sm">There is no season yet. <Link className="underline" href="/admin">Create the first season</Link>, add teams, then <Link className="underline" href="/admin/import">add players</Link>.</p>
          : <p className="text-sm text-muted-foreground">There is no season yet. The organisers will add you to a team, and your matches will show up here.</p>}
        {err && <p role="alert" className="text-sm text-destructive">{err}</p>}
      </div>
    );
  }
  return (
    <div className="space-y-5">
      <div className="hero-gradient card-elevated rounded-2xl p-5">
        <p className="text-xs font-medium uppercase tracking-widest text-gold">{season.status}</p>
        <h1 className="mt-1 text-2xl font-bold">{season.name}</h1>
        {me && <p className="mt-1 text-sm text-white/80">Welcome back, {me.name}</p>}
      </div>
      {err && <p role="alert" className="text-sm text-destructive">{err}</p>}
      <section aria-label="Live now" className="space-y-2">
        <h2 className="flex items-center gap-2 font-semibold"><span className="live-dot inline-block h-2 w-2 rounded-full bg-live" aria-hidden />Live now</h2>
        {live.length === 0 ? <p className="text-sm text-muted-foreground">No match is being played right now.</p>
          : <ul className="space-y-2">{live.map((f) => <li key={f.id}><FixtureCard f={f} /></li>)}</ul>}
      </section>
      <section aria-label="Next matches" className="space-y-2">
        <h2 className="font-semibold">Next matches</h2>
        {next.length === 0 ? <p className="text-sm text-muted-foreground">No upcoming matches yet. They appear here once the organisers publish the fixtures.</p>
          : <ul className="space-y-2">{next.map((f) => <li key={f.id}><FixtureCard f={f} /></li>)}</ul>}
      </section>
      <nav aria-label="Shortcuts" className="grid grid-cols-3 gap-2">
        <Link className={tile} href="/fixtures"><CalendarDays size={22} aria-hidden />All fixtures</Link>
        <Link className={tile} href="/standings"><Table2 size={22} aria-hidden />Table</Link>
        <Link className={tile} href="/leaderboards"><BarChart3 size={22} aria-hidden />Stats</Link>
      </nav>
    </div>
  );
}
