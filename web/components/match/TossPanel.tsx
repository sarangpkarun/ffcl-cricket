"use client";

import { useState } from "react";
import { btnCls, btnGhost, ErrorText } from "@/components/ui-bits";
import { post, type Live } from "@/lib/api";

export function TossPanel({ live, myTeamIds, onDone }: { live: Live; myTeamIds: number[]; onDone: () => void }) {
  const { match, toss, you } = live;
  const [err, setErr] = useState<string | null>(null);
  const run = async (path: string, body?: unknown) => {
    setErr(null);
    try { await post(`/matches/${match.id}/${path}`, body); onDone(); } catch (e) { setErr((e as Error).message); }
  };
  if (match.status !== "toss") return null;
  const winner = toss?.winner_team_id;
  const iAmWinnerCaptain = winner != null && myTeamIds.includes(winner);

  return (
    <section className="space-y-3 rounded-lg border-2 border-foreground p-4">
      <h2 className="font-medium">🪙 Toss</h2>
      {!winner && <p className="text-sm">Waiting for the umpire to record the toss winner.</p>}
      {winner && <p className="text-sm">Won by <b>{match.teams[String(winner)]}</b>{toss?.decision ? ` · elected to ${toss.decision === "bat" ? "bat" : "bowl"}` : " · waiting for their choice"}</p>}
      {winner && !toss?.decision && (iAmWinnerCaptain || you.official) && (
        <div className="flex gap-3">
          <button className={`${btnGhost} flex-1`} onClick={() => run("toss/decision", { decision: "bat" })}>Bat first</button>
          <button className={`${btnGhost} flex-1`} onClick={() => run("toss/decision", { decision: "bowl" })}>Bowl first</button>
        </div>
      )}
      {you.official && (
        <div className="space-y-2">
          <p className="text-xs text-muted-foreground">Umpire: record the winner of the coin toss</p>
          <div className="flex gap-3">
            {[match.team_a_id, match.team_b_id].map((t) => (
              <button key={t} className={`${btnGhost} flex-1`} onClick={() => run("toss/winner", { winner_team_id: t })}>{match.teams[String(t)]}</button>
            ))}
          </div>
          <button className={btnCls} disabled={!toss?.decision} onClick={() => run("toss/confirm")}>Confirm toss</button>
        </div>
      )}
      <ErrorText msg={err} />
    </section>
  );
}
