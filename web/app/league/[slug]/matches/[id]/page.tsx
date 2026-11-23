import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { JsonLd } from "@/components/JsonLd";
import { LiveMatch } from "@/components/league/LiveMatch";
import { Skeleton } from "@/components/league/PublicBits";
import { SITE, pub, pubPlain, type PubMatch } from "@/lib/public";

type P = { params: Promise<{ slug: string; id: string }> };

const title = (m: PubMatch) => {
  const { match } = m.live;
  return `${match.teams[String(match.team_a_id)]} vs ${match.teams[String(match.team_b_id)]}`;
};

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug, id } = await params;
  const m = await pubPlain<PubMatch>(`/matches/${id}`);
  if (!m) return { title: "Match not found", robots: { index: false } };
  const t = title(m);
  const desc = m.live.match.result ?? `${t} in ${m.season.name}. Follow the scorecard live.`;
  return { title: t, description: desc, alternates: { canonical: `/league/${slug}/matches/${id}` }, openGraph: { title: t, description: desc } };
}

function matchJsonLd(m: PubMatch, slug: string, id: string) {
  const { match } = m.live;
  return {
    "@context": "https://schema.org", "@type": "SportsEvent", name: title(m), url: `${SITE}/league/${slug}/matches/${id}`,
    startDate: m.scheduled_at ?? undefined, sport: "Digit cricket",
    eventStatus: match.status === "abandoned" ? "https://schema.org/EventCancelled" : "https://schema.org/EventScheduled",
    homeTeam: { "@type": "SportsTeam", name: match.teams[String(match.team_a_id)] },
    awayTeam: { "@type": "SportsTeam", name: match.teams[String(match.team_b_id)] },
  };
}

async function Content({ params }: P) {
  const { slug, id } = await params;
  const m = await pub<PubMatch>(`/matches/${id}`);
  if (!m || m.season.slug !== slug) notFound();
  const { match } = m.live;
  return (
    <div className="space-y-4">
      <JsonLd data={matchJsonLd(m, slug, id)} />
      <p className="text-sm">
        <Link className="underline" href={`/league/${slug}/teams/${match.team_a_id}`}>{match.teams[String(match.team_a_id)]}</Link>
        {" vs "}
        <Link className="underline" href={`/league/${slug}/teams/${match.team_b_id}`}>{match.teams[String(match.team_b_id)]}</Link>
        {m.round_label ? ` · ${m.round_label}` : ""}
      </p>
      <LiveMatch matchId={Number(id)} initial={m.live} slug={slug} />
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
