import Link from "next/link";
import { SeasonOverview } from "@/components/league/SeasonOverview";
import { pub, type SeasonListItem } from "@/lib/public";

/** What a signed-out visitor sees at "/": the current season at a glance. */
export async function Landing() {
  const seasons = (await pub<SeasonListItem[]>("/seasons")) ?? [];
  const current = seasons.find((s) => s.status === "active") ?? seasons[0];
  return (
    <div className="space-y-5">
      <section className="space-y-2">
        <h1 className="text-2xl font-bold">FFCL digit cricket league</h1>
        <p className="text-sm text-muted-foreground">Follow every match live, check the table and see who is leading the stats. Players and umpires sign in to play.</p>
        <p className="flex flex-wrap gap-3 text-sm">
          <Link prefetch={false} className="underline" href="/league">All seasons</Link>
          <Link prefetch={false} className="underline" href="/league/history">History</Link>
          {current && <Link prefetch={false} className="underline" href={`/league/${current.slug}/rules`}>How it is played</Link>}
          <Link prefetch={false} className="underline" href="/register">Join the league</Link>
        </p>
      </section>
      {current ? (
        <>
          <h2 className="text-lg font-semibold"><Link prefetch={false} href={`/league/${current.slug}`}>{current.name}</Link></h2>
          <SeasonOverview slug={current.slug} />
        </>
      ) : <p className="text-sm text-muted-foreground">No season is public yet. Check back soon.</p>}
    </div>
  );
}
