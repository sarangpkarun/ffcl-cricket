import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Tie } from "@/components/league/Bracket";
import { Skeleton } from "@/components/league/PublicBits";
import { StandingsTable } from "@/components/league/StandingsTable";
import { pub, type PubBracket, type PubStandings } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Points table", description: "The FFCL points table with net run rate and knockouts.", alternates: { canonical: `/league/${slug}/table` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const [data, bracket] = await Promise.all([pub<PubStandings>(`/seasons/${slug}/standings`), pub<PubBracket>(`/seasons/${slug}/bracket`)]);
  if (!data) notFound();
  const champion = bracket?.champion ?? data.season.champion;
  return (
    <div className="space-y-4">
      <h2 className="sr-only">Points table</h2>
      {champion && <p role="status" className="rounded-lg bg-foreground px-4 py-3 text-center font-medium text-background">🏆 {champion.name} are champions</p>}
      <StandingsTable data={data} teamHref={(id) => `/league/${slug}/teams/${id}`} prefetch={false} />
      {bracket?.stage && (
        <section className="space-y-2" aria-label="Knockouts">
          <h2 className="font-medium">Knockouts</h2>
          <ul className="space-y-2">{bracket.matches.map((m) => <li key={m.id}><Tie m={m} href={`/league/${slug}/matches/${m.id}`} prefetch={false} /></li>)}</ul>
        </section>
      )}
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
