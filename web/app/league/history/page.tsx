import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { Skeleton } from "@/components/league/PublicBits";
import { pub, type PubHistory } from "@/lib/public";

export const metadata: Metadata = { title: "History", description: "Past FFCL seasons: champions, final tables and top performers.", alternates: { canonical: "/league/history" } };

async function Content() {
  const rows = (await pub<PubHistory[]>("/history")) ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No finished seasons yet.</p>;
  const lead = (slug: string, label: string, l: PubHistory["top_batter"]) => l && (
    <li>{label}: {l.player.id !== null ? <Link className="underline" href={`/league/${slug}/players/${l.player.id}`}>{l.player.name}</Link> : l.player.name} {l.value}</li>
  );
  return (
    <>
      {rows.map((s) => (
        <section key={s.season.id} aria-label={s.season.name} className="space-y-2 rounded-lg border p-3 text-sm">
          <h2 className="font-medium"><Link href={`/league/${s.season.slug}`} className="underline">{s.season.name}</Link> <span className="text-xs text-muted-foreground">{s.teams} teams · {s.matches} matches</span></h2>
          {s.champion && <p className="font-medium">🏆 Champions: {s.champion.name}</p>}
          <ol className="divide-y rounded border">
            {s.table.map((r) => <li key={r.position} className="flex justify-between p-2"><span>{r.position}. {r.team}</span><span className="text-muted-foreground">P{r.played} W{r.won} L{r.lost} · {r.points} pts · {r.nrr >= 0 ? "+" : ""}{r.nrr.toFixed(3)}</span></li>)}
          </ol>
          <ul className="space-y-0.5">
            {lead(s.season.slug, "Most runs", s.top_batter)}
            {lead(s.season.slug, "Most wickets", s.top_bowler)}
            {lead(s.season.slug, "Most player of the match awards", s.most_awards)}
          </ul>
        </section>
      ))}
    </>
  );
}

export default function Page() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Season history</h1>
      <Suspense fallback={<Skeleton />}><Content /></Suspense>
    </div>
  );
}
