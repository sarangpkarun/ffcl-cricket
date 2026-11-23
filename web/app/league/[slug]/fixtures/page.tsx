import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { FixtureList, Section, Skeleton } from "@/components/league/PublicBits";
import { pub, type PubFixture } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Fixtures", description: "Upcoming and live FFCL matches.", alternates: { canonical: `/league/${slug}/fixtures` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const [live, next] = await Promise.all([pub<PubFixture[]>(`/seasons/${slug}/fixtures?status=live`), pub<PubFixture[]>(`/seasons/${slug}/fixtures?status=upcoming`)]);
  if (!live || !next) notFound();
  return (
    <div className="space-y-5">
      <h2 className="sr-only">Fixtures</h2>
      {live.length > 0 && <Section title="Live now"><FixtureList items={live} slug={slug} empty="" /></Section>}
      <Section title="Upcoming"><FixtureList items={next} slug={slug} empty="No upcoming matches yet." /></Section>
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
