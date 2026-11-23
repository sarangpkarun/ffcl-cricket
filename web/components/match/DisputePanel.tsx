"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, inputCls } from "@/components/ui-bits";
import { api, post } from "@/lib/api";
import { KIND_LABEL, STATUS_LABEL, type DisputeRow, when } from "@/lib/disputes";

type Info = { can_raise: boolean; reason: string | null; role: string | null; kinds: string[]; deadline: string | null; disputes: DisputeRow[] };

/** On a finished match: raise a dispute (if you may), and see the ones you are allowed to see. */
export function DisputePanel({ matchId }: { matchId: number }) {
  const router = useRouter();
  const [info, setInfo] = useState<Info | null>(null);
  const [kind, setKind] = useState("");
  const [body, setBody] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Info>(`/matches/${matchId}/disputes`).then(setInfo).catch(() => {}), [matchId]);
   
  useEffect(() => { void load(); }, [load]);
  if (!info || (!info.can_raise && info.disputes.length === 0 && !info.role)) return null;

  return (
    <section aria-label="Disputes" className="space-y-2 rounded-lg border p-3">
      <h2 className="font-medium">Disputes</h2>
      {info.disputes.length > 0 && (
        <ul className="space-y-1 text-sm">
          {info.disputes.map((d) => (
            <li key={d.id}><Link className="underline" href={`/disputes/${d.id}`}>{KIND_LABEL[d.kind]} · {d.raised_by.name}</Link> <span className="text-muted-foreground">· {STATUS_LABEL[d.status]}</span></li>
          ))}
        </ul>
      )}
      {!info.can_raise && info.reason && <p className="text-sm text-muted-foreground">{info.reason}</p>}
      {info.can_raise && (
        <details>
          <summary className="cursor-pointer text-sm font-medium">Raise a dispute</summary>
          <form className="mt-2 space-y-2" onSubmit={async (e) => {
            e.preventDefault();
            setErr(null);
            try { const r = await post<{ id: number }>("/disputes", { kind, body, match_id: matchId }); router.push(`/disputes/${r.id}`); }
            catch (x) { setErr((x as Error).message); await load(); }
          }}>
            {info.deadline && info.kinds.includes("scoring") && <p className="text-xs text-muted-foreground">You can dispute this result until {when(info.deadline)}.</p>}
            <select aria-label="What is it about" className={inputCls} required value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">What is it about?</option>
              {info.kinds.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
            </select>
            <textarea aria-label="What happened" className={inputCls} rows={4} required minLength={10} maxLength={2000} placeholder="Explain what happened, as clearly as you can." value={body} onChange={(e) => setBody(e.target.value)} />
            <ErrorText msg={err} />
            <button className={btnCls}>Send to the organisers</button>
            <p className="text-xs text-muted-foreground">Only you, the captains involved and the organisers can see this.</p>
          </form>
        </details>
      )}
    </section>
  );
}
