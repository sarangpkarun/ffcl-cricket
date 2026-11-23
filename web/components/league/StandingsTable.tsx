import Link from "next/link";
import type { Standings } from "@/lib/api";

export const TIEBREAK_LABEL: Record<string, string> = { points: "points", nrr: "net run rate", wins: "wins", head_to_head: "head-to-head", name: "name" };

export function Form({ form }: { form: string[] }) {
  const tone: Record<string, string> = { W: "bg-green-600 text-white", L: "bg-red-600 text-white", T: "bg-amber-500 text-white", N: "bg-muted text-foreground" };
  return (
    <span className="flex gap-0.5" aria-label={`Form: ${form.join(" ")}`}>
      {form.map((f, i) => <span key={i} className={`inline-flex h-4 w-4 items-center justify-center rounded-sm text-[10px] ${tone[f] ?? ""}`}>{f}</span>)}
    </span>
  );
}

/** The points table. Shared by the signed-in app and the public site; only the team link differs. */
export function StandingsTable({ data, teamHref }: { data: Standings; teamHref: (teamId: number) => string }) {
  return (
    <>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm" aria-label="Points table">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-2 py-2">#</th><th className="py-2">Team</th>
              <th className="px-1 text-right">P</th><th className="px-1 text-right">W</th><th className="px-1 text-right">L</th>
              <th className="px-1 text-right">T</th><th className="px-1 text-right">Pts</th><th className="px-2 text-right">NRR</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r, i) => (
              <tr key={r.team.id} aria-label={`${r.position}. ${r.team.name}`}
                className={`border-t ${r.qualified ? "border-l-4 border-l-green-600" : ""} ${i === data.qualifiers - 1 ? "border-b-2 border-b-foreground/30" : ""}`}>
                <td className="px-2 py-2">{r.position}</td>
                <td className="py-2">
                  <Link href={teamHref(r.team.id)} className="flex items-center gap-2 font-medium">
                    <span className="inline-block h-3 w-3 rounded-full" style={{ background: r.team.color ?? "#999" }} />{r.team.name}
                  </Link>
                  {r.form.length > 0 && <Form form={r.form} />}
                </td>
                <td className="px-1 text-right">{r.played}</td><td className="px-1 text-right">{r.won}</td>
                <td className="px-1 text-right">{r.lost}</td><td className="px-1 text-right">{r.tied}</td>
                <td className="px-1 text-right font-semibold">{r.points}{r.adjustments !== 0 && <sup title={`${r.adjustments > 0 ? "+" : ""}${r.adjustments} adjustment`}>*</sup>}</td>
                <td className="px-2 text-right tabular-nums">{r.nrr > 0 ? "+" : ""}{r.nrr.toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Top {data.qualifiers} qualify. Win {data.points.win}, tie {data.points.tie}, loss {data.points.loss}.
        Level on points? {data.tiebreakers.filter((t) => t !== "points" && t !== "name").map((t) => TIEBREAK_LABEL[t] ?? t).join(", then ")}.
        {data.rows.some((r) => r.adjustments !== 0) && " * includes a points adjustment."}
      </p>
      {!data.league_complete && data.matches_counted > 0 && <p className="text-xs text-muted-foreground">{data.pending_matches.length} league match(es) still to play.</p>}
      {data.matches_counted === 0 && <p className="text-sm text-muted-foreground">No results yet. The table fills in as matches finish.</p>}
    </>
  );
}
