import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { FixtureList, Skeleton } from "@/components/league/PublicBits";
import { pub, type PubFixture } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Results", description: "Every finished FFCL match, newest first.", alternates: { canonical: `/league/${slug}/results` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const done = await pub<PubFixture[]>(`/seasons/${slug}/fixtures?status=completed`);
  if (!done) notFound();
  return <section aria-label="Results" className="space-y-2"><h2 className="sr-only">Results</h2><FixtureList items={done} slug={slug} empty="No results yet." /></section>;
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
