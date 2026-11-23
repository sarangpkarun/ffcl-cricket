"use client";

import Link from "next/link";
import { AnalyticsPanel } from "@/components/match/AnalyticsPanel";
import { Scoreboard, overLabel } from "@/components/match/Scoreboard";
import type { Live } from "@/lib/api";
import { usePublicLive } from "@/lib/usePublicLive";

const STATE: Record<string, string> = {
  awaiting_signal: "waiting for the umpire's signal",
  submissions_open: "players are choosing their digits",
  locked: "digits locked, waiting for the reveal",
  revealed: "digits revealed",
  resolved: "over complete",
};

function Over({ over }: { over: NonNullable<Live["over"]> & { bowler?: string | null; batter?: string | null } }) {
  return (
    <section aria-label="Current over" className="space-y-1 rounded-lg border p-3 text-sm">
      <p className="font-medium">Over {over.number} · {STATE[over.state] ?? over.state}</p>
      <p className="text-xs text-muted-foreground">{overLabel(over.over_type)}</p>
      {(over.bowler || over.batter) && <p>Bowler {over.bowler ?? "?"} {over.submitted.bowl ? "✅" : "⏳"} · Batter {over.batter ?? "?"} {over.submitted.bat ? "✅" : "⏳"}</p>}
      {over.digits && <p className="text-xs text-muted-foreground">Digits are revealed ball by ball on the scorecard below.</p>}
    </section>
  );
}

/** A public match page that keeps itself up to date. The first render comes from the server. */
export function LiveMatch({ matchId, initial, slug }: { matchId: number; initial: Live; slug: string }) {
  const { live, connected } = usePublicLive(matchId, initial);
  const finished = live.match.status === "completed" || live.match.status === "abandoned";
  const potm = live.match.potm;
  return (
    <div className="space-y-4">
      {!finished && <p className={`text-xs ${connected ? "text-green-700" : "text-amber-700"}`} aria-live="polite">{connected ? "● Live" : "○ Updating every few seconds"}</p>}
      <Scoreboard live={live} />
      {live.innings.some((i) => i.status !== "pending") && <AnalyticsPanel matchId={matchId} seq={live.match.seq} publicSite />}
      {live.over && live.over.state !== "resolved" && !finished && <Over over={live.over} />}
      {potm && <p className="text-sm">⭐ Player of the match: {potm.id !== null ? <Link className="underline" href={`/league/${slug}/players/${potm.id}`}>{potm.name}</Link> : potm.name}</p>}
    </div>
  );
}
