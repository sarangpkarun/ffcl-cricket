import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { TeamAnalyticsView } from "@/components/league/Analytics";
import { FixtureList, Section, Skeleton } from "@/components/league/PublicBits";
import { pub, pubPlain, type PubTeam, type TeamAnalytics } from "@/lib/public";

type P = { params: Promise<{ slug: string; id: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { slug, id } = await params;
  const t = await pubPlain<PubTeam>(`/teams/${id}`);
  if (!t) return { title: "Team not found", robots: { index: false } };
  return { title: t.team.name, description: `${t.team.name} in ${t.season.name}: results, fixtures, squad and stats.`, alternates: { canonical: `/league/${slug}/teams/${id}` } };
}

async function Content({ params }: P) {
  const { slug, id } = await params;
  const [t, an] = await Promise.all([pub<PubTeam>(`/teams/${id}`), pub<TeamAnalytics>(`/teams/${id}/analytics`)]);
  if (!t || t.season.slug !== slug) notFound();
  const row = t.table;
  return (
    <div className="space-y-5">
      <h2 className="flex items-center gap-2 text-lg font-semibold">
        <span className="h-4 w-4 rounded-full" style={{ background: t.team.color ?? "#999" }} aria-hidden />{t.team.name}
      </h2>
      {row && row.played > 0 && (
        <p className="text-sm">#{row.position} · P{row.played} W{row.won} L{row.lost}{row.tied ? ` T${row.tied}` : ""} · {row.points} pts · NRR {row.nrr >= 0 ? "+" : ""}{row.nrr.toFixed(3)}{t.win_pct !== null && ` · Win ${t.win_pct}%`}</p>
      )}
      <Section title="Squad">
        <ul className="grid gap-2 sm:grid-cols-2">
          {t.members.map((m) => (
            <li key={m.player.player_code} className="rounded-lg border p-3 text-sm">
              {m.player.id !== null ? <Link className="font-medium underline" href={`/league/${slug}/players/${m.player.id}`}>{m.player.name}</Link> : <span className="font-medium">{m.player.name}</span>}
              {m.captain && " ©"}
            </li>
          ))}
        </ul>
      </Section>
      {t.players.length > 0 && (
        <Section title="Player figures">
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full text-sm" aria-label="Player figures">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Player</th><th className="px-2 text-right">M</th><th className="px-2 text-right">Runs</th><th className="px-3 text-right">Wkts</th></tr></thead>
              <tbody>
                {t.players.filter((p) => p.player).map((p) => (
                  <tr key={p.player!.player_code} className="border-t">
                    <td className="px-3 py-2">{p.player!.id !== null ? <Link className="underline" href={`/league/${slug}/players/${p.player!.id}`}>{p.player!.name}</Link> : p.player!.name}</td>
                    <td className="px-2 text-right">{p.matches}</td><td className="px-2 text-right">{p.runs}</td><td className="px-3 text-right">{p.wickets}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Section>
      )}
      {an && an.played > 0 && <Section title="Analytics"><TeamAnalyticsView data={an} /></Section>}
      <Section title="Matches"><FixtureList items={t.fixtures} slug={slug} empty="No matches yet." /></Section>
    </div>
  );
}

export default function Page({ params }: P) {
  return <Suspense fallback={<Skeleton />}><Content params={params} /></Suspense>;
}
