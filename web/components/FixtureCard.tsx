"use client";

import Link from "next/link";
import { Trophy } from "lucide-react";
import type { Fixture } from "@/lib/api";

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString([], { weekday: "short", day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "Time to be confirmed";

const isLive = (f: Fixture) => ["innings1", "break", "innings2"].includes(f.status);

function Badge({ f }: { f: Fixture }) {
  const live = isLive(f);
  const text = !f.published ? "Draft" : f.paused ? "Paused" : live ? "Live" : f.status === "completed" ? "Final" : f.status === "abandoned" ? "Abandoned" : f.status === "toss" ? "Toss" : "Scheduled";
  const tone = !f.published ? "border-warning text-warning" : live && !f.paused ? "border-live bg-live text-white" : "bg-muted text-muted-foreground border-transparent";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>
      {live && f.published && !f.paused && <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-white" aria-hidden />}
      {text}
    </span>
  );
}

export function FixtureCard({ f }: { f: Fixture }) {
  const dot = (c: string | null) => <span className="inline-block h-3.5 w-3.5 shrink-0 rounded-full ring-2 ring-white" style={{ background: c ?? "#999" }} />;
  const live = isLive(f) && f.published;
  return (
    <Link
      href={`/matches/${f.id}`}
      className={`card-elevated block space-y-2 rounded-2xl border bg-card p-4 transition active:scale-[0.99] ${live ? "border-live/40 ring-1 ring-live/20" : ""}`}
      aria-label={`Match ${f.match_no}: ${f.team_a.name} vs ${f.team_b.name}`}
    >
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>{f.round_label ?? "Match"} · #{f.match_no}</span>
        <Badge f={f} />
      </div>
      <div className="space-y-1 text-base font-semibold">
        <p className="flex items-center gap-2">{dot(f.team_a.color)} {f.team_a.name}</p>
        <p className="flex items-center gap-2">{dot(f.team_b.color)} {f.team_b.name}</p>
      </div>
      <p className="text-sm text-muted-foreground">{when(f.scheduled_at)}{f.umpire ? ` · umpire ${f.umpire}` : ""}</p>
      {f.result && <p className="flex items-center gap-1.5 rounded-lg bg-accent px-2 py-1 text-sm font-medium text-accent-foreground"><Trophy size={15} aria-hidden />{f.result}</p>}
    </Link>
  );
}
