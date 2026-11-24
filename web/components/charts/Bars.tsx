export type BarSeries = { label: string; color: string; values: (number | null)[] };

const W = 320, H = 170, L = 28, R = 6, T = 10, B = 34;

/** Grouped vertical bars, one group per label (an over, a match). `marks` puts a short tag under a group (for powerplays). */
export function Bars({ labels, series, marks, title, unit = "runs" }: { labels: string[]; series: BarSeries[]; marks?: (string | null)[]; title: string; unit?: string }) {
  const max = Math.max(5, ...series.flatMap((s) => s.values.map((v) => v ?? 0)));
  const top = Math.ceil(max / 5) * 5;
  const gw = (W - L - R) / Math.max(labels.length, 1);
  const bw = Math.min(22, (gw - 6) / series.length);
  const y = (v: number) => H - B - ((H - T - B) * v) / top;
  return (
    <figure className="space-y-1">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${title}. ${labels.map((l, i) => `${l}: ${series.map((s) => `${s.label} ${s.values[i] ?? 0}`).join(", ")}`).join("; ")}`} className="w-full">
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={L} x2={W - R} y1={y(top * f)} y2={y(top * f)} stroke="currentColor" strokeOpacity="0.12" />
            <text x={L - 4} y={y(top * f) + 3} fontSize="9" textAnchor="end" fill="currentColor" fillOpacity="0.6">{Math.round(top * f)}</text>
          </g>
        ))}
        {labels.map((l, i) => {
          const gx = L + i * gw + (gw - bw * series.length) / 2;
          return (
            <g key={i}>
              {series.map((s, k) => {
                const v = s.values[i];
                return v === null || v === undefined ? null : (
                  <g key={s.label}>
                    <rect x={gx + k * bw} y={y(v)} width={bw - 1} height={Math.max(0, H - B - y(v))} fill={s.color} rx="2" />
                    {v > 0 && <text x={gx + k * bw + (bw - 1) / 2} y={y(v) - 2} fontSize="8" textAnchor="middle" fill="currentColor">{v}</text>}
                  </g>
                );
              })}
              <text x={L + i * gw + gw / 2} y={H - 18} fontSize="9" textAnchor="middle" fill="currentColor" fillOpacity="0.7">{l}</text>
              {marks?.[i] && <text x={L + i * gw + gw / 2} y={H - 6} fontSize="8" textAnchor="middle" fill="#b45309" fontWeight="600">{marks[i]}</text>}
            </g>
          );
        })}
      </svg>
      <figcaption className="flex flex-wrap gap-3 text-xs">
        {series.map((s) => <span key={s.label} className="flex items-center gap-1"><span className="inline-block h-2 w-3 rounded" style={{ background: s.color }} />{s.label} ({unit})</span>)}
        {marks?.some(Boolean) && <span><b className="text-warning">PP</b> powerplay over</span>}
      </figcaption>
      <table className="sr-only">
        <caption>{title}</caption>
        <thead><tr><th>Item</th>{series.map((s) => <th key={s.label}>{s.label}</th>)}</tr></thead>
        <tbody>{labels.map((l, i) => <tr key={i}><td>{l}</td>{series.map((s) => <td key={s.label}>{s.values[i] ?? 0}</td>)}</tr>)}</tbody>
      </table>
    </figure>
  );
}

/** One horizontal bar per label, as a percentage: used for digit habits. */
export function Share({ rows, title }: { rows: { label: string; value: number; note?: string }[]; title: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul aria-label={title} className="space-y-1 text-sm">
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-2">
          <span className="w-4 text-right tabular-nums">{r.label}</span>
          <span className="relative h-4 flex-1 rounded bg-muted" aria-hidden><span className="absolute inset-y-0 left-0 rounded bg-primary" style={{ width: `${(100 * r.value) / max}%` }} /></span>
          <span className="w-24 text-xs tabular-nums text-muted-foreground">{r.value}%{r.note ? ` · ${r.note}` : ""}</span>
        </li>
      ))}
    </ul>
  );
}
