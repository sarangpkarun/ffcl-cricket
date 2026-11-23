import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Skeleton } from "@/components/league/PublicBits";
import { pub, type PubRules } from "@/lib/public";

type P = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug } = await params;
  return { title: "Rules", description: "How FFCL digit cricket is played, scored and ranked.", alternates: { canonical: `/league/${slug}/rules` } };
}

async function Content({ params }: P) {
  const { slug } = await params;
  const data = await pub<PubRules>(`/seasons/${slug}/rules`);
  if (!data) notFound();
  return (
    <div className="space-y-5">
      <h2 className="sr-only">Rules</h2>
      {data.sections.map((s) => (
        <section key={s.title} aria-label={s.title} className="space-y-1">
          <h3 className="font-medium">{s.title}</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">{s.items.map((i) => <li key={i}>{i}</li>)}</ul>
        </section>
      ))}
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
