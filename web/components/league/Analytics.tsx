import Link from "next/link";
import { Bars, Share } from "@/components/charts/Bars";
import { Worm } from "@/components/charts/Worm";
import { TYPE_LABEL, TYPE_ORDER, type DigitCounts, type MatchAnalytics, type PlayerAnalytics, type SeasonAnalytics, type TeamAnalytics } from "@/lib/analytics";

const COLORS = ["#2563eb", "#dc2626"];
const val = (v: number | null, suffix = "") => (v === null ? "–" : `${v}${suffix}`);

function Card({ label, value }: { label: string; value: string | number }) {
  return <div className="rounded-lg border p-2 text-center"><p className="text-lg font-semibold">{value}</p><p className="text-xs text-muted-foreground">{label}</p></div>;
}

function Digits({ title, d, available }: { title: string; d: { batting: DigitCounts; bowling: DigitCounts } | null; available: boolean }) {
  if (!available || !d) {
    return <section aria-label={title} className="space-y-1"><h3 className="font-medium">{title}</h3><p className="text-sm text-muted-foreground">Digit habits are shown once the season is finished. Until then they stay private, so nobody can use them to guess digits.</p></section>;
  }
  const rows = (c: DigitCounts) => Object.keys(c.counts).map((k) => ({ label: k, value: c.percent[k], note: `${c.counts[k]}` }));
  return (
    <section aria-label={title} className="space-y-2">
      <h3 className="font-medium">{title}</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><p className="mb-1 text-xs text-muted-foreground">As batter · {d.batting.total} balls{d.batting.most_used ? ` · favourite ${d.batting.most_used}` : ""}</p><Share title="Batting digits" rows={rows(d.batting)} /></div>
        <div><p className="mb-1 text-xs text-muted-foreground">As bowler · {d.bowling.total} balls{d.bowling.most_used ? ` · favourite ${d.bowling.most_used}` : ""}</p><Share title="Bowling digits" rows={rows(d.bowling)} /></div>
      </div>
    </section>
  );
}

/** Worm, runs per over and powerplay split for one match. */
export function MatchAnalyticsView({ data }: { data: MatchAnalytics }) {
  const played = data.innings.filter((i) => i.balls > 0);
  if (played.length === 0) return <p className="text-sm text-muted-foreground">Charts appear once the first over is played.</p>;
  const total = data.overs_in_match * data.balls_per_over;
  const series = played.map((i, k) => ({ label: `${i.team.name} ${i.total}/${i.wickets}`, color: COLORS[k % 2], points: i.worm }));
  const labels = Array.from({ length: data.overs_in_match }, (_, o) => String(o + 1));
  const marks = labels.map((_, o) => (data.over_types[String(o + 1)] === "normal" ? null : "PP"));
  return (
    <div className="space-y-4">
      <section aria-label="Worm" className="space-y-1"><h3 className="font-medium">How the innings built up</h3><Worm series={series} balls={total} /></section>
      <section aria-label="Runs per over" className="space-y-1">
        <h3 className="font-medium">Runs in each over</h3>
        <Bars title="Runs in each over" labels={labels} marks={marks} series={played.map((i, k) => ({ label: i.team.name ?? `Innings ${i.number}`, color: COLORS[k % 2], values: labels.map((_, o) => i.overs.find((r) => r.over === o + 1)?.runs ?? null) }))} />
        {data.biggest_over && <p className="text-xs text-muted-foreground">Biggest over: {data.biggest_over.runs} runs in over {data.biggest_over.over}.</p>}
      </section>
      <section aria-label="Powerplays" className="space-y-1">
        <h3 className="font-medium">Powerplay split</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Over type</th>{played.map((i) => <th key={i.number} className="px-2 text-right">{i.team.name}</th>)}</tr></thead>
            <tbody>
              {TYPE_ORDER.map((t) => (
                <tr key={t} className="border-t"><td className="px-3 py-2">{TYPE_LABEL[t]}</td>{played.map((i) => <td key={i.number} className="px-2 text-right tabular-nums">{i.by_type[t].balls ? `${i.by_type[t].runs} runs, ${i.by_type[t].wickets} wkt${i.by_type[t].wickets === 1 ? "" : "s"} (${i.by_type[t].run_rate.toFixed(2)}/over)` : "–"}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
        {played.some((i) => i.penalty_runs !== 0) && <p className="text-xs text-muted-foreground">Penalty runs are in the totals above but not in the lines and bars, which show the ball-by-ball scoring.</p>}
      </section>
    </div>
  );
}

function TypeTable({ rows, last, lastKey }: { rows: Record<string, { balls: number; runs: number; wickets: number } & Record<string, number>>; last: string; lastKey: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Over type</th><th className="px-2 text-right">Balls</th><th className="px-2 text-right">Runs</th><th className="px-2 text-right">Wkts</th><th className="px-3 text-right">{last}</th></tr></thead>
        <tbody>
          {TYPE_ORDER.map((t) => (
            <tr key={t} className="border-t"><td className="px-3 py-2">{TYPE_LABEL[t]}</td><td className="px-2 text-right">{rows[t].balls}</td><td className="px-2 text-right">{rows[t].runs}</td><td className="px-2 text-right">{rows[t].wickets}</td><td className="px-3 text-right tabular-nums">{rows[t].balls ? rows[t][lastKey].toFixed(2) : "–"}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function TeamAnalyticsView({ data }: { data: TeamAnalytics }) {
  if (data.played === 0) return <p className="text-sm text-muted-foreground">Analytics appear after the first finished match.</p>;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2">
        <Card label="Batting first" value={`${data.batting_first.won}/${data.batting_first.played}`} />
        <Card label="Chasing" value={`${data.chasing.won}/${data.chasing.played}`} />
        <Card label="Average score" value={val(data.average_for)} />
        <Card label="Average conceded" value={val(data.average_against)} />
        <Card label="Highest" value={val(data.highest)} />
        <Card label="Lowest" value={val(data.lowest)} />
      </div>
      <section aria-label="Toss" className="space-y-1">
        <h3 className="font-medium">Toss</h3>
        <p className="text-sm">Won {data.toss.won}, lost {data.toss.lost}. Chose to bat {data.toss.chose_bat}, to bowl {data.toss.chose_bowl}.</p>
        <p className="text-xs text-muted-foreground">Won the match after winning the toss: {val(data.toss.win_pct_after_winning, "%")} · after losing it: {val(data.toss.win_pct_after_losing, "%")}</p>
      </section>
      <section aria-label="Batting by over type" className="space-y-1"><h3 className="font-medium">Batting by over type</h3><TypeTable rows={data.batting_by_type} last="Runs/over" lastKey="run_rate" /></section>
      <section aria-label="Bowling by over type" className="space-y-1"><h3 className="font-medium">Bowling by over type</h3><TypeTable rows={data.bowling_by_type} last="Economy" lastKey="economy" /></section>
    </div>
  );
}

export function PlayerAnalyticsView({ data, playerHref }: { data: PlayerAnalytics; playerHref: (id: number) => string }) {
  const form = data.form;
  const name = (r: { user_id: number | null; name: string | null }) => (r.user_id !== null ? <Link className="underline" href={playerHref(r.user_id)}>{r.name}</Link> : r.name);
  return (
    <div className="space-y-4">
      {form.length === 0 ? <p className="text-sm text-muted-foreground">Analytics appear after the first finished match.</p> : (
        <section aria-label="Form" className="space-y-1">
          <h3 className="font-medium">Form: last {form.length} matches</h3>
          <Bars title="Runs and wickets in recent matches" unit="" labels={form.map((f) => `M${f.match_no}`)}
            series={[{ label: "Runs", color: COLORS[0], values: form.map((f) => f.runs) }, { label: "Wickets", color: COLORS[1], values: form.map((f) => f.wickets) }]} />
        </section>
      )}
      <section aria-label="By over type" className="space-y-1">
        <h3 className="font-medium">Batting by over type</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Over type</th><th className="px-2 text-right">Balls</th><th className="px-2 text-right">Runs</th><th className="px-2 text-right">Out</th><th className="px-3 text-right">SR</th></tr></thead>
            <tbody>{TYPE_ORDER.map((t) => <tr key={t} className="border-t"><td className="px-3 py-2">{TYPE_LABEL[t]}</td><td className="px-2 text-right">{data.batting_by_type[t].balls}</td><td className="px-2 text-right">{data.batting_by_type[t].runs}</td><td className="px-2 text-right">{data.batting_by_type[t].outs}</td><td className="px-3 text-right tabular-nums">{data.batting_by_type[t].balls ? data.batting_by_type[t].strike_rate.toFixed(1) : "–"}</td></tr>)}</tbody>
          </table>
        </div>
        <h3 className="pt-2 font-medium">Bowling by over type</h3>
        <TypeTable rows={data.bowling_by_type} last="Economy" lastKey="economy" />
      </section>
      {data.versus_bowlers.length > 0 && (
        <section aria-label="Against bowlers" className="space-y-1">
          <h3 className="font-medium">Batting against</h3>
          <ul className="divide-y rounded-lg border text-sm">
            {data.versus_bowlers.slice(0, 5).map((r, i) => <li key={`${r.user_id}-${i}`} className="flex justify-between p-2"><span>{name(r)}</span><span className="text-muted-foreground">{r.runs} off {r.balls}{r.outs ? ` · out ${r.outs}×` : ""}</span></li>)}
          </ul>
        </section>
      )}
      {data.versus_batters.length > 0 && (
        <section aria-label="Against batters" className="space-y-1">
          <h3 className="font-medium">Bowling against</h3>
          <ul className="divide-y rounded-lg border text-sm">
            {data.versus_batters.slice(0, 5).map((r, i) => <li key={`${r.user_id}-${i}`} className="flex justify-between p-2"><span>{name(r)}</span><span className="text-muted-foreground">{r.runs} off {r.balls}{r.wickets ? ` · ${r.wickets} wkt${r.wickets > 1 ? "s" : ""}` : ""}</span></li>)}
          </ul>
        </section>
      )}
      <Digits title="Digit habits" d={data.digits} available={data.digits_available} />
    </div>
  );
}

export function SeasonInsightsView({ data, teamHref }: { data: SeasonAnalytics; teamHref: (id: number) => string }) {
  const s = data.summary;
  if (s.matches === 0) return <p className="text-sm text-muted-foreground">Insights appear after the first finished match.</p>;
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-3 gap-2">
        <Card label="Matches" value={s.matches} />
        <Card label="Avg 1st innings" value={val(s.average_first_innings)} />
        <Card label="Avg 2nd innings" value={val(s.average_second_innings)} />
        <Card label="Won batting first" value={val(s.bat_first_pct, "%")} />
        <Card label="Won chasing" value={val(s.chase_pct, "%")} />
        <Card label="Toss winner won" value={val(s.toss.toss_winner_pct, "%")} />
      </div>
      <p className="text-xs text-muted-foreground">{s.decided} decided matches, {s.ties} tied. Highest total {val(s.highest_total)}, lowest {val(s.lowest_total)}. The toss winner chose to bat {s.toss.chose_bat} times and to bowl {s.toss.chose_bowl} times.</p>
      <section aria-label="By over type" className="space-y-1">
        <h3 className="font-medium">Scoring by over type, whole league</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Over type</th><th className="px-2 text-right">Runs/over</th><th className="px-3 text-right">Wkts/over</th></tr></thead>
            <tbody>{TYPE_ORDER.map((t) => <tr key={t} className="border-t"><td className="px-3 py-2">{TYPE_LABEL[t]}</td><td className="px-2 text-right tabular-nums">{s.by_type[t].balls ? s.by_type[t].run_rate.toFixed(2) : "–"}</td><td className="px-3 text-right tabular-nums">{s.by_type[t].balls ? s.by_type[t].wickets_per_over.toFixed(2) : "–"}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
      <section aria-label="Teams" className="space-y-1">
        <h3 className="font-medium">Teams compared</h3>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Team</th><th className="px-2 text-right">Avg for</th><th className="px-2 text-right">Avg against</th><th className="px-2 text-right">Bat 1st</th><th className="px-3 text-right">Chasing</th></tr></thead>
            <tbody>
              {data.teams.map((t) => (
                <tr key={t.team.id} className="border-t">
                  <td className="px-3 py-2"><Link className="underline" href={teamHref(t.team.id)}>{t.team.name}</Link></td>
                  <td className="px-2 text-right tabular-nums">{val(t.average_for)}</td><td className="px-2 text-right tabular-nums">{val(t.average_against)}</td>
                  <td className="px-2 text-right">{t.batting_first.won}/{t.batting_first.played}</td><td className="px-3 text-right">{t.chasing.won}/{t.chasing.played}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <Digits title="Digits chosen across the season" d={data.digits} available={data.digits_available} />
    </div>
  );
}
