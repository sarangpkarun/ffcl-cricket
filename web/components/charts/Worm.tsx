export type WormSeries = { label: string; color: string; points: { ball: number; runs: number; wicket: boolean }[] };

const W = 320, H = 190, L = 34, R = 10, T = 10, B = 26;

/** Runs after every ball for each side, with a dot where a wicket fell. A table below says the same in words. */
export function Worm({ series, balls }: { series: WormSeries[]; balls: number }) {
  const max = Math.max(10, ...series.flatMap((s) => s.points.map((p) => p.runs)));
  const top = Math.ceil(max / 10) * 10;
  const x = (b: number) => L + ((W - L - R) * b) / balls;
  const y = (r: number) => H - B - ((H - T - B) * r) / top;
  const path = (s: WormSeries) => [{ ball: 0, runs: 0 }, ...s.points].map((p, i) => `${i ? "L" : "M"}${x(p.ball).toFixed(1)},${y(p.runs).toFixed(1)}`).join(" ");
  const summary = series.map((s) => `${s.label} ${s.points.at(-1)?.runs ?? 0} runs, ${s.points.filter((p) => p.wicket).length} wickets`).join("; ");
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Runs after each ball. ${summary}`} className="w-full">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(top * f)} y2={y(top * f)} stroke="currentColor" strokeOpacity="0.12" />
            <text x={L - 4} y={y(top * f) + 3} fontSize="9" textAnchor="end" fill="currentColor" fillOpacity="0.6">{Math.round(top * f)}</text>
          </g>
        ))}
        {Array.from({ length: Math.floor(balls / 6) + 1 }, (_, o) => (
          <text key={o} x={x(o * 6)} y={H - 8} fontSize="9" textAnchor="middle" fill="currentColor" fillOpacity="0.6">{o}</text>
        ))}
        <text x={W - R} y={H - 1} fontSize="8" textAnchor="end" fill="currentColor" fillOpacity="0.5">overs</text>
        {series.map((s) => (
          <g key={s.label}>
            <path d={path(s)} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" />
            {s.points.filter((p) => p.wicket).map((p) => <circle key={p.ball} cx={x(p.ball)} cy={y(p.runs)} r="3.2" fill="#dc2626" stroke="white" strokeWidth="0.8" />)}
          </g>
        ))}
      </svg>
      <figcaption className="flex flex-wrap gap-3 text-xs">
        {series.map((s) => <span key={s.label} className="flex items-center gap-1"><span className="inline-block h-2 w-4 rounded" style={{ background: s.color }} />{s.label}</span>)}
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-2 rounded-full bg-destructive" />wicket</span>
      </figcaption>
      <table className="sr-only">
        <caption>Runs after each over</caption>
        <thead><tr><th>Over</th>{series.map((s) => <th key={s.label}>{s.label}</th>)}</tr></thead>
        <tbody>
          {Array.from({ length: Math.floor(balls / 6) }, (_, o) => (
            <tr key={o}><td>{o + 1}</td>{series.map((s) => <td key={s.label}>{s.points.find((p) => p.ball === (o + 1) * 6)?.runs ?? s.points.at(-1)?.runs ?? 0}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
