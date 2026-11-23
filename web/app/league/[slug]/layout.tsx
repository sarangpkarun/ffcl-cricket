import { notFound } from "next/navigation";
import { Suspense } from "react";
import { SeasonTabs } from "@/components/league/SeasonTabs";
import { pub, type Overview, type SeasonListItem } from "@/lib/public";

async function Header({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const [ov, all] = await Promise.all([pub<Overview>(`/seasons/${slug}`), pub<SeasonListItem[]>("/seasons")]);
  if (!ov) notFound();
  return (
    <header className="space-y-2">
      <h1 className="text-xl font-semibold">{ov.season.name}</h1>
      <SeasonTabs slug={slug} seasons={(all ?? []).map((s) => ({ slug: s.slug, name: s.name }))} />
    </header>
  );
}

export default function Layout({ children, params }: { children: React.ReactNode; params: Promise<{ slug: string }> }) {
  return (
    <div className="space-y-5">
      <Suspense fallback={<div className="h-20" />}><Header params={params} /></Suspense>
      {children}
    </div>
  );
}
