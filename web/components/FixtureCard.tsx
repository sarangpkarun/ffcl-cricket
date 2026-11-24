"use client";

import Link from "next/link";
import type { Fixture } from "@/lib/api";

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "Time to be confirmed";

function Badge({ f }: { f: Fixture }) {
  const live = ["innings1", "break", "innings2"].includes(f.status);
  const text = !f.published ? "Draft" : f.paused ? "Paused" : live ? "● Live" : f.status === "completed" ? "Final" : f.status === "abandoned" ? "Abandoned" : f.status === "toss" ? "Toss" : "Scheduled";
  const tone = !f.published ? "border-amber-500 text-amber-700" : live ? "border-green-600 text-green-700" : "text-muted-foreground";
  return <span className={`rounded-full border px-2 py-0.5 text-xs ${tone}`}>{text}</span>;
}

export function FixtureCard({ f }: { f: Fixture }) {
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
