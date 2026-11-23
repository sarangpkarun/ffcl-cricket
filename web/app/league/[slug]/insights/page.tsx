import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { SeasonInsightsView } from "@/components/league/Analytics";
import { Skeleton } from "@/components/league/PublicBits";
import { pub, type SeasonAnalytics } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Insights", description: "Averages, toss and chase records, powerplay scoring and how the teams compare.", alternates: { canonical: `/league/${slug}/insights` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const data = await pub<SeasonAnalytics>(`/seasons/${slug}/analytics`);
  if (!data) notFound();
  return <div className="space-y-4"><h2 className="sr-only">Insights</h2><SeasonInsightsView data={data} teamHref={(id) => `/league/${slug}/teams/${id}`} prefetch={false} /></div>;
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
