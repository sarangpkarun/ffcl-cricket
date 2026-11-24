import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { Skeleton } from "@/components/league/PublicBits";
import { pub, type SeasonListItem } from "@/lib/public";

export const metadata: Metadata = { title: "Seasons", description: "Every FFCL season: fixtures, results, table and stats.", alternates: { canonical: "/league" } };

async function Seasons() {
  const seasons = (await pub<SeasonListItem[]>("/seasons")) ?? [];
  if (seasons.length === 0) return <p className="text-sm text-muted-foreground">No seasons are public yet.</p>;
  return (
    <ul className="space-y-2">
      {seasons.map((s) => (
        <li key={s.id}>
          <Link prefetch={false} href={`/league/${s.slug}`} className="block card-elevated rounded-2xl border bg-card p-4">
            <p className="font-medium">{s.name}</p>
            <p className="text-sm text-muted-foreground">{s.teams} teams · {s.matches} matches · {s.status}{s.champion ? ` · 🏆 ${s.champion}` : ""}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function Page() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold text-primary">Seasons</h1>
      <Suspense fallback={<Skeleton />}><Seasons /></Suspense>
    </div>
  );
}
