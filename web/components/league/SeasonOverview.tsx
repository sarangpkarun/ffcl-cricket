import Link from "next/link";
import { notFound } from "next/navigation";
import { FixtureList, Section } from "@/components/league/PublicBits";
import { pub, type Overview } from "@/lib/public";

export async function SeasonOverview({ slug }: { slug: string }) {
  const ov = await pub<Overview>(`/seasons/${slug}`);
  if (!ov) notFound();
  const top = ov.table.slice(0, Math.max(ov.qualifiers, 4));
  return (
    <div className="space-y-5">
      {ov.champion && <p role="status" className="rounded-lg bg-foreground px-4 py-3 text-center font-medium text-background">🏆 {ov.champion.name} are champions</p>}
      {ov.live.length > 0 && <Section title="Live now" label="Live now"><FixtureList items={ov.live} slug={slug} empty="" /></Section>}
      <Section title="Next matches"><FixtureList items={ov.next} slug={slug} empty="No upcoming matches yet." /></Section>
      <Section title="Latest results"><FixtureList items={ov.latest} slug={slug} empty="No results yet." /></Section>
      <Section title="Table" label="Table snapshot">
        {top.every((r) => r.played === 0) ? <p className="text-sm text-muted-foreground">The table fills in as matches finish.</p> : (
          <ol className="divide-y rounded-lg border text-sm">
            {top.map((r) => (
              <li key={r.team.id} className="flex items-center justify-between p-3">
                <span>{r.position}. <Link prefetch={false} className="font-medium underline" href={`/league/${slug}/teams/${r.team.id}`}>{r.team.name}</Link></span>
                <span className="text-muted-foreground">P{r.played} · <b className="text-foreground">{r.points}</b> pts</span>
              </li>
            ))}
          </ol>
        )}
        <Link prefetch={false} className="text-sm underline" href={`/league/${slug}/table`}>Full table and knockouts</Link>
      </Section>
      {(ov.leaders.most_runs.length > 0 || ov.leaders.most_wickets.length > 0) && (
        <Section title="Leaders" label="Leaders">
          <div className="grid gap-3 sm:grid-cols-2">
            {([["Most runs", ov.leaders.most_runs], ["Most wickets", ov.leaders.most_wickets]] as const).map(([title, rows]) => (
              <div key={title} className="rounded-lg border p-3 text-sm">
                <p className="mb-1 text-xs text-muted-foreground">{title}</p>
                <ol className="space-y-1">
                  {rows.map((r) => (
                    <li key={`${r.player?.id ?? r.player?.name}`} className="flex justify-between">
                      <span>{r.player && r.player.id !== null ? <Link prefetch={false} className="underline" href={`/league/${slug}/players/${r.player.id}`}>{r.player.name}</Link> : r.player?.name}</span>
                      <b>{r.value}</b>
                    </li>
                  ))}
                </ol>
              </div>
            ))}
          </div>
          <Link prefetch={false} className="text-sm underline" href={`/league/${slug}/stats`}>All leaderboards</Link>
        </Section>
      )}
    </div>
  );
}

