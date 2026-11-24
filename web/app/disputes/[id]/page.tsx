"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, post } from "@/lib/api";
import { ACTION_LABEL, KIND_LABEL, STATUS_LABEL, type DisputeDetail, when } from "@/lib/disputes";

type Adj = { id: number; team: { name: string | null }; points: number; reason: string; voided: boolean };

function Decide({ d, reload }: { d: DisputeDetail; reload: () => void }) {
  const [outcome, setOutcome] = useState("");
  const [action, setAction] = useState("none");
  const [adj, setAdj] = useState("");
  const [adjs, setAdjs] = useState<Adj[]>([]);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Adj[]>(`/seasons/${d.season.id}/adjustments`).then(setAdjs).catch(() => {}); }, [d.season.id]);
  const send = async (path: "resolve" | "dismiss") => {
    setErr(null);
    try { await post(`/admin/disputes/${d.id}/${path}`, { outcome, action: path === "dismiss" ? "none" : action, adjustment_id: action === "points_adjusted" && adj ? Number(adj) : null }); reload(); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <section aria-label="Decide" className="space-y-2 rounded-lg border-2 border-foreground p-3">
      <h2 className="font-medium">Decide</h2>
      <p className="text-xs text-muted-foreground">Make any change first, with the tools you already have, then record it here.</p>
      <div className="flex flex-wrap gap-3 text-sm">
        {d.match && <Link className="underline" href={`/matches/${d.match.id}`}>Open the match (corrections, reversals)</Link>}
        <Link className="underline" href="/admin/adjustments">Points adjustments</Link>
      </div>
      <textarea aria-label="Outcome" className={inputCls} rows={3} minLength={10} maxLength={2000} placeholder="What was decided, and why. Everyone involved will read this." value={outcome} onChange={(e) => setOutcome(e.target.value)} />
      <select aria-label="What was done" className={inputCls} value={action} onChange={(e) => setAction(e.target.value)}>
        {Object.entries(ACTION_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      {action === "points_adjusted" && (
        <select aria-label="Which adjustment" className={inputCls} value={adj} onChange={(e) => setAdj(e.target.value)}>
          <option value="">Which adjustment?</option>
          {adjs.filter((a) => !a.voided).map((a) => <option key={a.id} value={a.id}>{a.team.name} {a.points > 0 ? "+" : ""}{a.points}: {a.reason}</option>)}
        </select>
      )}
      <ErrorText msg={err} />
      <div className="flex gap-2">
        <button className={btnCls} onClick={() => void send("resolve")}>Resolve</button>
        <button className={btnGhost} onClick={() => void send("dismiss")}>Dismiss</button>
      </div>
    </section>
  );
}

function Detail() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<DisputeDetail | null>(null);
  const [msg, setMsg] = useState("");
  const [internal, setInternal] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<DisputeDetail>(`/disputes/${id}`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message)), [id]);
   
  useEffect(() => { void load(); }, [load]);
  if (!d) return <ErrorText msg={err} />;
  const run = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); await load(); } catch (x) { setErr((x as Error).message); } };
  const v = d.viewer;

  return (
    <div className="space-y-4">
      <header>
        <p className="text-xs text-muted-foreground">{d.season.name}{d.match ? ` · Match ${d.match.match_no}: ${d.match.teams}` : ""}</p>
        <h1 className="text-2xl font-bold text-primary">{KIND_LABEL[d.kind]}</h1>
        <p className="text-sm"><b>{STATUS_LABEL[d.status]}</b>{d.assigned_to ? ` · looked at by ${d.assigned_to}` : ""}</p>
      </header>
      <ErrorText msg={err} />
      {d.outcome && (
        <section aria-label="Outcome" className="rounded-lg bg-muted p-3 text-sm">
          <p className="font-medium">{STATUS_LABEL[d.status]} by {d.resolved_by}{d.resolved_at ? `, ${when(d.resolved_at)}` : ""}</p>
          <p className="whitespace-pre-wrap">{d.outcome}</p>
          {d.resolution && <p className="mt-1 text-xs text-muted-foreground">{ACTION_LABEL[d.resolution.action]}</p>}
        </section>
      )}
      <section className="space-y-1 card-elevated rounded-2xl border bg-card p-3 text-sm">
        <p className="text-xs text-muted-foreground">Raised by {d.raised_by.name} ({d.raised_by.as.replace("_", " ")}) · {when(d.created_at)}{d.against ? ` · about ${d.against}` : ""}</p>
        <p className="whitespace-pre-wrap">{d.body}</p>
        {d.match_result && <p className="text-xs text-muted-foreground">Result: {d.match_result}</p>}
        {d.match && <Link className="text-xs underline" href={`/matches/${d.match.id}`}>Open the match</Link>}
      </section>

      <section aria-label="Conversation" className="space-y-2">
        <h2 className="font-medium">Conversation</h2>
        {d.messages.length === 0 && <p className="text-sm text-muted-foreground">No messages yet.</p>}
        <ul className="space-y-2">
          {d.messages.map((m) => (
            <li key={m.id} className={`card-elevated rounded-2xl border bg-card p-3 text-sm ${m.internal ? "border-dashed bg-warning/10" : ""}`}>
              <p className="text-xs text-muted-foreground">{m.author.name} · {when(m.created_at)}{m.internal && " · private note, only organisers see this"}</p>
              <p className="whitespace-pre-wrap">{m.body}</p>
            </li>
          ))}
        </ul>
        {v.can_message && (
          <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); await run(async () => { await post(`/disputes/${id}/messages`, { body: msg, internal }); setMsg(""); }); }}>
            <textarea aria-label="Your message" className={inputCls} rows={3} required maxLength={2000} value={msg} onChange={(e) => setMsg(e.target.value)} />
            {v.level === "admin" && <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={internal} onChange={(e) => setInternal(e.target.checked)} /> Private note (only organisers see it)</label>}
            <button className={btnGhost}>Send</button>
          </form>
        )}
      </section>

      {v.can_withdraw && <button className={btnGhost} onClick={() => run(() => post(`/disputes/${id}/withdraw`))}>Withdraw this dispute</button>}
      {v.can_take && <button className={btnGhost} onClick={() => run(() => post(`/admin/disputes/${id}/take`))}>I will look into this</button>}
      {v.can_decide && <Decide d={d} reload={() => void load()} />}
      {v.can_reopen && (
        <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); await run(async () => { await post(`/admin/disputes/${id}/reopen`, { reason }); setReason(""); }); }}>
          <Field label="Reason for reopening" required minLength={3} value={reason} onChange={(e) => setReason(e.target.value)} />
          <button className={btnGhost}>Reopen</button>
        </form>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Detail /></RequireAuth>;
}
