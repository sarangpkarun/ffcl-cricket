"use client";

import { useEffect, useState } from "react";
import { MatchAnalyticsView } from "@/components/league/Analytics";
import { api } from "@/lib/api";
import type { MatchAnalytics } from "@/lib/analytics";

/** Collapsible match analytics. Loads when opened and refreshes as the match changes. */
export function AnalyticsPanel({ matchId, seq, publicSite = false }: { matchId: number; seq: number; publicSite?: boolean }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<MatchAnalytics | null>(null);
  useEffect(() => {
    if (!open) return;
    const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const load = publicSite
      ? fetch(`${API}/public/matches/${matchId}/analytics`, { cache: "no-store" }).then((r) => (r.ok ? (r.json() as Promise<MatchAnalytics>) : null))
      : api<MatchAnalytics>(`/matches/${matchId}/analytics`);
    void load.then((d) => d && setData(d)).catch(() => {});
  }, [open, matchId, seq, publicSite]);
  return (
    <details className="card-elevated rounded-2xl border bg-card p-3" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer font-medium">Match analytics</summary>
      <div className="mt-3">{data ? <MatchAnalyticsView data={data} /> : open ? <p className="text-sm text-muted-foreground">Loading…</p> : null}</div>
    </details>
  );
}
