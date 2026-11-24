import Link from "next/link";

export type Totals = {
  matches: number; innings: number; runs: number; balls: number; fours: number; sixes: number; outs: number; not_outs: number; highest: number;
  strike_rate: number; average: number | null; bowl_innings: number; overs: string; runs_conceded: number; wickets: number; economy: number;
  best_bowling: string | null; potm: number;
};
export type History = {
  match_id: number; match_no: number; round_label: string | null; against: string | null; team: string | null; won: boolean | null;
  batted: boolean; runs: number; balls: number; out: boolean; bowled: boolean; bowl_balls: number; runs_conceded: number; wickets: number; potm: boolean;
};

function Stat({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border p-2 text-center"><p className="text-lg font-semibold">{value}</p><p className="text-xs text-muted-foreground">{label}</p></div>;
}

export function BattingBowling({ t }: { t: Totals }) {
  return (
    <>
      <section aria-label="Batting" className="space-y-2">
        <h2 className="font-medium">Batting</h2>
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Matches" value={t.matches} />
          <Stat label="Runs" value={t.runs} />
          <Stat label="Highest" value={t.highest} />
          <Stat label="Strike rate" value={t.strike_rate.toFixed(2)} />
          <Stat label="Average" value={t.average === null ? "–" : t.average.toFixed(2)} />
          <Stat label="4s / 6s" value={`${t.fours} / ${t.sixes}`} />
        </div>
      </section>
      <section aria-label="Bowling" className="space-y-2">
        <h2 className="font-medium">Bowling</h2>
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Overs" value={t.overs} />
          <Stat label="Wickets" value={t.wickets} />
          <Stat label="Economy" value={t.economy.toFixed(2)} />
          <Stat label="Runs given" value={t.runs_conceded} />
          <Stat label="Best" value={t.best_bowling ?? "–"} />
          <Stat label="Player of match" value={t.potm} />
        </div>
      </section>
    </>
  );
}

export function MatchHistory({ history, matchHref, prefetch = true }: { history: History[]; matchHref: (id: number) => string; prefetch?: boolean }) {
  return (
    <section aria-label="Match history" className="space-y-1">
      <h2 className="font-medium">Match history</h2>
      {history.length === 0 && <p className="text-sm text-muted-foreground">No matches yet.</p>}
      <ul className="space-y-2">
        {history.map((h) => (
          <li key={h.match_id}>
            <Link href={matchHref(h.match_id)} prefetch={prefetch} className="block card-elevated rounded-2xl border bg-card p-3 text-sm">
              <span className="font-medium">{h.round_label ?? `Match ${h.match_no}`}</span> vs {h.against}
              {h.won !== null && <span className={h.won ? " text-success" : " text-destructive"}> · {h.won ? "Won" : "Lost"}</span>}
              {h.potm && " ⭐"}
              <span className="block text-xs text-muted-foreground">
                {h.batted ? `${h.runs} off ${h.balls}${h.out ? "" : "*"}` : "did not bat"}{h.bowled ? ` · ${h.wickets}/${h.runs_conceded} (${h.bowl_balls} balls)` : ""}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
