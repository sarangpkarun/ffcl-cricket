import Link from "next/link";
import { SeasonOverview } from "@/components/league/SeasonOverview";
import { pub, type SeasonListItem } from "@/lib/public";

/** What a signed-out visitor sees at "/": the current season at a glance. */
export async function Landing() {
  const seasons = (await pub<SeasonListItem[]>("/seasons")) ?? [];
  const current = seasons.find((s) => s.status === "active") ?? seasons[0];
  return (
    <div className="space-y-5">
      <section className="hero-gradient card-elevated space-y-3 rounded-2xl p-6">
        <h1 className="text-3xl font-bold">FFCL digit cricket league</h1>
        <p className="text-sm text-white/85">Follow every match live, check the table and see who is leading the stats. Players and umpires sign in to play.</p>
        <p className="flex flex-wrap items-center gap-3 text-sm">
          <Link prefetch={false} className="text-white underline" href="/league">All seasons</Link>
          <Link prefetch={false} className="text-white underline" href="/league/history">History</Link>
          {current && <Link prefetch={false} className="text-white underline" href={`/league/${current.slug}/rules`}>How it is played</Link>}
          <Link prefetch={false} className="rounded-full bg-white px-4 py-2 font-semibold text-primary" href="/register">Join the league</Link>
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
