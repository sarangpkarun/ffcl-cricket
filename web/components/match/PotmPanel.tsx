"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, inputCls } from "@/components/ui-bits";
import { api, put } from "@/lib/api";

type Line = { player: { id: number; name: string } | null; team?: string; runs?: number; balls?: number; wickets?: number; runs_conceded?: number; score?: number };
type Potm = { eligible: boolean; can_choose: boolean; award: Line | null; suggestion: Line | null; candidates: Line[] };

const describe = (l: Line) => [l.runs || l.balls ? `${l.runs} off ${l.balls}` : null, l.wickets ? `${l.wickets} wkt${l.wickets > 1 ? "s" : ""}` : null].filter(Boolean).join(", ");

export function PotmPanel({ matchId, seq }: { matchId: number; seq: number }) {
  const [d, setD] = useState<Potm | null>(null);
  const [pick, setPick] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Potm>(`/matches/${matchId}/potm`).then(setD).catch((e) => setErr(e.message)), [matchId]);
  useEffect(() => { void load(); }, [load, seq]);
  if (!d || !d.eligible) return <ErrorText msg={err} />;

  return (
    <section aria-label="Player of the match" className="space-y-2 rounded-lg border p-3">
      <h2 className="font-medium">⭐ Player of the match</h2>
      {d.award?.player
        ? <p className="text-sm"><Link className="font-medium underline" href={`/players/${d.award.player.id}`}>{d.award.player.name}</Link>{d.award.team && ` (${d.award.team})`}{describe(d.award) && ` · ${describe(d.award)}`}</p>
        : <p className="text-sm text-muted-foreground">Not chosen yet.</p>}
      <ErrorText msg={err} />
      {d.can_choose && (
        <form className="space-y-2" onSubmit={async (e) => {
          e.preventDefault();
          setErr(null);
          try { await put(`/matches/${matchId}/potm`, { user_id: Number(pick) }); setPick(""); await load(); } catch (x) { setErr((x as Error).message); }
        }}>
          {d.suggestion?.player && <p className="text-xs text-muted-foreground">Suggested: {d.suggestion.player.name} ({describe(d.suggestion)})</p>}
          <select aria-label="Choose player of the match" className={inputCls} required value={pick} onChange={(e) => setPick(e.target.value)}>
            <option value="">Choose a player</option>
            {d.candidates.map((c) => c.player && <option key={c.player.id} value={c.player.id}>{c.player.name} · {c.team} · {describe(c) || "did not bat or bowl"}</option>)}
          </select>
          <button className={btnCls}>{d.award ? "Change player of the match" : "Award player of the match"}</button>
        </form>
      )}
    </section>
  );
}
