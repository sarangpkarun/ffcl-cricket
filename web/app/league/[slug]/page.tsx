import type { Metadata } from "next";
import { Suspense } from "react";
import { Skeleton } from "@/components/league/PublicBits";
import { SeasonOverview } from "@/components/league/SeasonOverview";
import { pubPlain, type Overview } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  const ov = await pubPlain<Overview>(`/seasons/${slug}`);
  if (!ov) return { title: "Season not found", robots: { index: false } };
  const lead = ov.table[0];
  return { title: ov.season.name, description: `${ov.season.name}: live scores, fixtures, results, points table and stats.${lead && lead.played ? ` ${lead.team.name} lead the table.` : ""}`,
    alternates: { canonical: `/league/${slug}` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  return <SeasonOverview slug={slug} />;
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
