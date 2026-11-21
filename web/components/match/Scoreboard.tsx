import type { InningsCard, Live } from "@/lib/api";

const OVER_LABEL: Record<string, string> = {
  normal: "Normal over",
  bowling_pp: "Bowling powerplay: batter must use 5 and 6 once each",
  batting_pp: "Batting powerplay: bowler must use 5 and 6 once each",
};
export const overLabel = (t: string) => OVER_LABEL[t] ?? t;

function Ball({ b }: { b: { runs: number; wicket: boolean } }) {
  return (
    <span className={`inline-flex h-7 w-7 items-center justify-center rounded-full border text-xs ${b.wicket ? "bg-red-600 text-white" : ""}`}>
      {b.wicket ? "W" : b.runs}
    </span>
  );
}

function Innings({ inn, live }: { inn: InningsCard; live: Live }) {
  const name = live.match.teams[String(inn.batting_team_id)];
  const chasing = inn.target !== null && inn.status !== "pending";
  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div>
        <p className="text-xs text-muted-foreground">Innings {inn.number} · {inn.status}</p>
        <p className="text-sm font-medium">{name} batting</p>
        <p className="text-3xl font-bold">
          {inn.runs}/{inn.wickets} <span className="text-base font-normal text-muted-foreground">({inn.overs} ov)</span>
        </p>
        <p className="text-sm text-muted-foreground">
          RR {inn.run_rate.toFixed(2)}
          {chasing && inn.status === "active" && inn.required_rate !== null && ` · need ${inn.target! - inn.runs} off ${inn.balls_remaining} · RRR ${inn.required_rate.toFixed(2)}`}
          {chasing && inn.status !== "active" && ` · target ${inn.target}`}
          {inn.extras !== 0 && ` · penalty ${inn.extras > 0 ? "+" : ""}${inn.extras}`}
        </p>
      </div>

      {inn.batting.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th>Batter</th><th className="text-right">R</th><th className="text-right">B</th><th className="text-right">4s</th><th className="text-right">6s</th><th className="text-right">SR</th></tr>
          </thead>
          <tbody>
            {inn.batting.map((b) => (
              <tr key={b.id}>
                <td>{b.name}{!b.out && "*"}</td>
                <td className="text-right">{b.runs}</td><td className="text-right">{b.balls}</td>
                <td className="text-right">{b.fours}</td><td className="text-right">{b.sixes}</td>
                <td className="text-right">{b.strike_rate.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {inn.bowling.length > 0 && (
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr><th>Bowler</th><th className="text-right">O</th><th className="text-right">R</th><th className="text-right">W</th><th className="text-right">Econ</th></tr>
          </thead>
          <tbody>
            {inn.bowling.map((b) => (
              <tr key={b.id}>
                <td>{b.name}</td><td className="text-right">{b.overs}</td><td className="text-right">{b.runs}</td>
                <td className="text-right">{b.wickets}</td><td className="text-right">{b.economy.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {inn.timeline.map((o) => (
        <div key={o.over} className="flex items-center gap-1">
          <span className="w-12 text-xs text-muted-foreground">Over {o.over}</span>
          {o.balls.map((b) => <Ball key={b.ball} b={b} />)}
        </div>
      ))}
      {inn.penalties.filter((p) => !p.voided).map((p) => (
        <p key={p.id} className="text-xs text-muted-foreground">
          📢 {live.match.teams[String(p.team_id)]}: {p.runs ? `${p.runs > 0 ? "+" : ""}${p.runs} runs` : ""}{p.wickets ? ` ${p.wickets} wicket` : ""} ({p.reason})
        </p>
      ))}
    </section>
  );
}

export function Scoreboard({ live }: { live: Live }) {
  const { match } = live;
  const [a, b] = [match.teams[String(match.team_a_id)], match.teams[String(match.team_b_id)]];
  return (
    <div className="space-y-4">
      <header>
        <p className="text-xs text-muted-foreground">MATCH {match.match_no} · {match.status.toUpperCase()}{match.paused && " · PAUSED"}</p>
        <h1 className="text-xl font-semibold">{a} vs {b}</h1>
        {match.result && <p className="mt-1 rounded-md bg-muted px-3 py-2 font-medium">🏆 {match.result}</p>}
      </header>
      {live.innings.filter((i) => i.status !== "pending").map((i) => <Innings key={i.number} inn={i} live={live} />)}
    </div>
  );
}
