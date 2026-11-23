import Link from "next/link";

export type LeaderRow = { rank: number; player: { id: number | null; name: string } | null; team: { id: number; name: string } | null; value: number; detail: string };
export type LeaderBoard = { categories: { key: string; title: string; rows: LeaderRow[] }[]; minimums: { strike_rate_balls: number; economy_balls: number } };

const fmt = (key: string, v: number) => (key === "best_strike_rate" || key === "best_economy" ? v.toFixed(2) : key === "best_win_pct" ? `${v}%` : String(v));

/** The leaderboard cards. Shared by the signed-in app and the public site. */
export function Leaderboards({ data, playerHref, teamHref, prefetch = true }: { data: LeaderBoard; playerHref: (id: number) => string; teamHref: (id: number) => string; prefetch?: boolean }) {
  return (
    <>
      {data.categories.every((c) => c.rows.length === 0) && <p className="text-sm text-muted-foreground">No statistics yet. They appear once matches are played.</p>}
      {data.categories.map((c) => (
        <section key={c.key} aria-label={c.title} className="space-y-1">
          <h2 className="font-medium">{c.title}</h2>
          {c.key === "best_strike_rate" && <p className="text-xs text-muted-foreground">At least {data.minimums.strike_rate_balls} balls faced.</p>}
          {c.key === "best_economy" && <p className="text-xs text-muted-foreground">At least {data.minimums.economy_balls} balls bowled.</p>}
          {c.rows.length === 0 ? <p className="text-sm text-muted-foreground">Nobody yet.</p> : (
            <ol className="divide-y rounded-lg border">
              {c.rows.map((r) => (
                <li key={`${r.player?.id ?? r.player?.name ?? r.team?.id}`} className="flex items-center gap-3 p-3 text-sm">
                  <span className="w-5 text-muted-foreground">{r.rank}</span>
                  <span className="min-w-0 flex-1">
                    {r.player
                      ? (r.player.id !== null ? <Link href={playerHref(r.player.id)} prefetch={prefetch} className="font-medium underline">{r.player.name}</Link> : <span className="font-medium">{r.player.name}</span>)
                      : <Link href={teamHref(r.team?.id ?? 0)} prefetch={prefetch} className="font-medium underline">{r.team?.name}</Link>}
                    <span className="block truncate text-xs text-muted-foreground">{r.player ? `${r.team?.name ?? ""} · ` : ""}{r.detail}</span>
                  </span>
                  <span className="text-base font-semibold">{fmt(c.key, r.value)}</span>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </>
  );
}
