import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Leaderboards } from "@/components/league/Leaderboards";
import { Skeleton } from "@/components/league/PublicBits";
import { pub, type PubLeaders } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Leaderboards", description: "Most runs, most wickets, best strike rate and economy, and more.", alternates: { canonical: `/league/${slug}/stats` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const data = await pub<PubLeaders>(`/seasons/${slug}/leaderboards`);
  if (!data) notFound();
  return (
    <div className="space-y-4">
      <h2 className="sr-only">Leaderboards</h2>
      <Leaderboards data={data} playerHref={(id) => `/league/${slug}/players/${id}`} teamHref={(id) => `/league/${slug}/teams/${id}`} />
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
