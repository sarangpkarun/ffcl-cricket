import Link from "next/link";
import { LocalTime } from "@/components/league/LocalTime";
import type { PubFixture } from "@/lib/public";

const LIVE = ["innings1", "break", "innings2"];

export function statusText(f: Pick<PubFixture, "status" | "paused">) {
  if (f.paused) return "Paused";
  if (LIVE.includes(f.status)) return "● Live";
  if (f.status === "completed") return "Final";
  if (f.status === "abandoned") return "Abandoned";
  if (f.status === "toss") return "Toss";
  return "Scheduled";
}

export function FixtureCard({ f, slug }: { f: PubFixture; slug: string }) {
  const live = LIVE.includes(f.status);
  return (
    <Link href={`/league/${slug}/matches/${f.id}`} className={`block rounded-lg border p-3 ${live ? "border-foreground" : ""}`}>
      <p className="flex justify-between text-xs text-muted-foreground">
        <span>{f.round_label ?? `Match ${f.match_no}`}</span>
        <span className={live ? "font-semibold text-red-600" : ""}>{statusText(f)}</span>
      </p>
      <p className="font-medium">{f.team_a.name} <span className="text-muted-foreground">vs</span> {f.team_b.name}</p>
      {f.result ? <p className="text-sm">🏆 {f.result}</p> : <p className="text-sm text-muted-foreground"><LocalTime iso={f.scheduled_at} /></p>}
    </Link>
  );
}

export function FixtureList({ items, slug, empty }: { items: PubFixture[]; slug: string; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return <ul className="space-y-2">{items.map((f) => <li key={f.id}><FixtureCard f={f} slug={slug} /></li>)}</ul>;
}

export function Skeleton({ label = "Loading" }: { label?: string }) {
  return <div role="status" aria-label={label} className="space-y-3"><div className="h-6 w-1/3 animate-pulse rounded bg-muted" /><div className="h-24 animate-pulse rounded bg-muted" /><div className="h-24 animate-pulse rounded bg-muted" /></div>;
}

export function Section({ title, children, label }: { title: string; children: React.ReactNode; label?: string }) {
  return <section aria-label={label ?? title} className="space-y-2"><h2 className="font-medium">{title}</h2>{children}</section>;
}
