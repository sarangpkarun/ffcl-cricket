import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Skeleton } from "@/components/league/PublicBits";
import { BattingBowling, MatchHistory } from "@/components/league/PlayerStats";
import { pub, pubPlain, type PubPlayer } from "@/lib/public";

type P = { params: Promise<{ slug: string; id: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug, id } = await params;
  const p = await pubPlain<PubPlayer>(`/players/${id}?season=${encodeURIComponent(slug)}`);
  if (!p) return { title: "Player not found", robots: { index: false } };
  return { title: p.player.name, description: `${p.player.name} in ${p.season.name}: ${p.totals.runs} runs, ${p.totals.wickets} wickets in ${p.totals.matches} matches.`,
    alternates: { canonical: `/league/${slug}/players/${id}` } };
}

async function Content({ params }: P) {
  const { slug, id } = await params;
  const p = await pub<PubPlayer>(`/players/${id}?season=${encodeURIComponent(slug)}`);
  if (!p) notFound();
  return (
    <div className="space-y-5">
      <header>
        <h2 className="text-lg font-semibold">{p.player.name}</h2>
        <p className="text-sm text-muted-foreground">{p.player.player_code} · {p.season.name}</p>
      </header>
      <BattingBowling t={p.totals} />
      <MatchHistory history={p.history} matchHref={(mid) => `/league/${slug}/matches/${mid}`} />
      {p.other_seasons.length > 0 && (
        <section aria-label="Other seasons" className="space-y-1 text-sm">
          <h3 className="font-medium">Other seasons</h3>
          <ul className="flex flex-wrap gap-3">{p.other_seasons.map((s) => <li key={s.id}><Link className="underline" href={`/league/${s.slug}/players/${id}`}>{s.name}</Link></li>)}</ul>
        </section>
      )}
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
