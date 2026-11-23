"use client";

import { useEffect, useState } from "react";
import { PlayerAnalyticsView, TeamAnalyticsView } from "@/components/league/Analytics";
import { api } from "@/lib/api";
import type { PlayerAnalytics, TeamAnalytics } from "@/lib/analytics";

export function TeamAnalyticsBlock({ teamId }: { teamId: number | string }) {
  const [d, setD] = useState<TeamAnalytics | null>(null);
  useEffect(() => { api<TeamAnalytics>(`/teams/${teamId}/analytics`).then(setD).catch(() => {}); }, [teamId]);
  if (!d || d.played === 0) return null;
  return <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">Team analytics</summary><div className="mt-3"><TeamAnalyticsView data={d} /></div></details>;
}

export function PlayerAnalyticsBlock({ playerId, seasonId }: { playerId: number | string; seasonId: string }) {
  const [d, setD] = useState<PlayerAnalytics | null>(null);
  useEffect(() => { api<PlayerAnalytics>(`/players/${playerId}/analytics${seasonId ? `?season_id=${seasonId}` : ""}`).then(setD).catch(() => {}); }, [playerId, seasonId]);
  if (!d) return null;
  return <details className="rounded-lg border p-3"><summary className="cursor-pointer font-medium">Analytics</summary><div className="mt-3"><PlayerAnalyticsView data={d} playerHref={(id) => `/players/${id}`} /></div></details>;
}
