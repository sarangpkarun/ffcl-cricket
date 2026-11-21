"use client";

import { useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, inputCls } from "@/components/ui-bits";
import { post, type Live } from "@/lib/api";
import { show } from "./PlayerPanel";
import { overLabel } from "./Scoreboard";

type Person = { id: number; name: string | null };

export function UmpireConsole({ live, lineups, onDone }: { live: Live; lineups: Record<number, Person[]>; onDone: () => void }) {
  const { match, over } = live;
  const base = `/matches/${match.id}`;
  const [err, setErr] = useState<string | null>(null);
  const [bowler, setBowler] = useState("");
  const [batter, setBatter] = useState("");
  const [ov, setOv] = useState({ role: "bat", digits: "", reason: "" });
  const [pen, setPen] = useState({ team: "", runs: "", wickets: "", kind: "", reason: "" });
  const [fix, setFix] = useState({ innings: "1", over: "", ball: "", bat: "", bowl: "", reason: "" });

  const run = async (path: string, body?: unknown) => {
    setErr(null);
    try { await post(`${base}/${path}`, body); onDone(); return true; } catch (e) { setErr((e as Error).message); return false; }
  };
  const active = live.innings.find((i) => i.status === "active");
  const live_ = ["innings1", "innings2", "break"].includes(match.status);
  const needOver = (match.status === "innings1" || match.status === "innings2") && (!over || over.state === "resolved");

  return (
    <section className="space-y-4 rounded-lg border-2 border-foreground p-4">
      <h2 className="font-medium">🧑‍⚖️ Umpire console</h2>
      <ErrorText msg={err} />

      {match.status === "scheduled" && <button className={btnCls} onClick={() => run("toss/open")}>Open toss</button>}
      {match.status === "ready" && <button className={btnCls} onClick={() => run("start")}>Start match</button>}
      {match.status === "break" && <button className={btnCls} onClick={() => run("innings/next")}>Start second innings</button>}

      {needOver && active && (
        <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); await run("overs/start", { bowler_id: Number(bowler), batter_id: Number(batter) }); }}>
          <p className="text-sm font-medium">Start over {(active.timeline.length || 0) + 1}</p>
          <select className={inputCls} required value={bowler} onChange={(e) => setBowler(e.target.value)}>
            <option value="">Bowler ({match.teams[String(active.bowling_team_id)]})</option>
            {(lineups[active.bowling_team_id] ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <select className={inputCls} required value={batter} onChange={(e) => setBatter(e.target.value)}>
            <option value="">Batter ({match.teams[String(active.batting_team_id)]})</option>
            {(lineups[active.batting_team_id] ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className={btnCls}>Start over</button>
        </form>
      )}

      {over && over.state !== "resolved" && (
        <div className="space-y-3 rounded-md bg-muted p-3">
          <p className="text-sm font-medium">Over {over.number} · {over.state.replace("_", " ")}</p>
          <p className="text-xs text-muted-foreground">{overLabel(over.over_type)}</p>
          <p className="text-sm">Bowler {over.submitted.bowl ? "✅" : "⏳"} · Batter {over.submitted.bat ? "✅" : "⏳"}</p>
          {over.digits && <div className="text-sm"><p>Batter: {show(over.digits.bat)}</p><p>Bowler: {show(over.digits.bowl)}</p></div>}
          {over.state === "awaiting_signal" && <button className={btnCls} onClick={() => run("overs/current/signal")}>Send signal and open submissions</button>}
          {over.state === "submissions_open" && (
            <>
              <button className={btnCls} disabled={!(over.submitted.bat && over.submitted.bowl)} onClick={() => run("overs/current/lock")}>Lock submissions</button>
              <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); if (await run("overs/current/override", ov)) setOv({ ...ov, digits: "", reason: "" }); }}>
                <p className="text-xs text-muted-foreground">Enter digits on a player&apos;s behalf (logged)</p>
                <select className={inputCls} value={ov.role} onChange={(e) => setOv({ ...ov, role: e.target.value })}>
                  <option value="bat">Batter</option><option value="bowl">Bowler</option>
                </select>
                <Field label="Six digits" inputMode="numeric" required value={ov.digits} onChange={(e) => setOv({ ...ov, digits: e.target.value })} />
                <Field label="Reason" required minLength={3} value={ov.reason} onChange={(e) => setOv({ ...ov, reason: e.target.value })} />
                <button className={btnGhost}>Override</button>
              </form>
            </>
          )}
          {over.state === "locked" && <button className={btnCls} onClick={() => run("overs/current/reveal")}>Reveal digits</button>}
          {over.state === "revealed" && <button className={btnCls} onClick={() => run("overs/current/resolve")}>Calculate and publish over</button>}
        </div>
      )}

      {live_ && (
        <>
          <button className={btnGhost} onClick={() => run(match.paused ? "resume" : "pause")}>{match.paused ? "▶ Resume match" : "⏸ Pause match"}</button>

          <details className="space-y-2">
            <summary className="cursor-pointer text-sm font-medium">Apply penalty</summary>
            <form className="mt-2 space-y-2" onSubmit={async (e) => {
              e.preventDefault();
              const ok = await run("penalties", { team_id: Number(pen.team), kind: pen.kind, runs: Number(pen.runs || 0), wickets: Number(pen.wickets || 0), reason: pen.reason, idempotency_key: crypto.randomUUID() });
              if (ok) setPen({ team: "", runs: "", wickets: "", kind: "", reason: "" });
            }}>
              <select className={inputCls} required value={pen.team} onChange={(e) => setPen({ ...pen, team: e.target.value })}>
                <option value="">Team whose total changes</option>
                {[match.team_a_id, match.team_b_id].map((t) => <option key={t} value={t}>{match.teams[String(t)]}</option>)}
              </select>
              <Field label="Rule broken (e.g. late_submission)" required minLength={2} value={pen.kind} onChange={(e) => setPen({ ...pen, kind: e.target.value })} />
              <div className="flex gap-2">
                <Field label="Runs (+/-)" type="number" value={pen.runs} onChange={(e) => setPen({ ...pen, runs: e.target.value })} />
                <Field label="Wickets" type="number" min={0} value={pen.wickets} onChange={(e) => setPen({ ...pen, wickets: e.target.value })} />
              </div>
              <Field label="Reason" required minLength={3} value={pen.reason} onChange={(e) => setPen({ ...pen, reason: e.target.value })} />
              <button className={btnGhost}>Apply penalty</button>
            </form>
          </details>

          <details className="space-y-2">
            <summary className="cursor-pointer text-sm font-medium">Correct a ball</summary>
            <form className="mt-2 space-y-2" onSubmit={async (e) => {
              e.preventDefault();
              await run("balls/correct", { innings_number: Number(fix.innings), over_no: Number(fix.over), ball_no: Number(fix.ball), batter_digit: Number(fix.bat), bowler_digit: Number(fix.bowl), reason: fix.reason });
            }}>
              <div className="grid grid-cols-3 gap-2">
                <Field label="Innings" type="number" min={1} max={2} required value={fix.innings} onChange={(e) => setFix({ ...fix, innings: e.target.value })} />
                <Field label="Over" type="number" min={1} required value={fix.over} onChange={(e) => setFix({ ...fix, over: e.target.value })} />
                <Field label="Ball" type="number" min={1} max={6} required value={fix.ball} onChange={(e) => setFix({ ...fix, ball: e.target.value })} />
                <Field label="Batter digit" type="number" min={1} max={6} required value={fix.bat} onChange={(e) => setFix({ ...fix, bat: e.target.value })} />
                <Field label="Bowler digit" type="number" min={1} max={6} required value={fix.bowl} onChange={(e) => setFix({ ...fix, bowl: e.target.value })} />
              </div>
              <Field label="Reason" required minLength={3} value={fix.reason} onChange={(e) => setFix({ ...fix, reason: e.target.value })} />
              <button className={btnGhost}>Save correction</button>
            </form>
          </details>
        </>
      )}
    </section>
  );
}
