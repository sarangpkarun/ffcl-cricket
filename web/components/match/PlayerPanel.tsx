"use client";

import { useEffect, useState } from "react";
import { DigitKeypad } from "@/components/DigitKeypad";
import { ErrorText } from "@/components/ui-bits";
import { ApiError, post, type OverView } from "@/lib/api";
import { overLabel } from "./Scoreboard";

const EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣"];
export const show = (d: number[] | null) => (d ? d.map((x) => EMOJI[x - 1]).join(" ") : "—");

function Countdown({ to }: { to: string | null }) {
  const [left, setLeft] = useState<number | null>(null);
  useEffect(() => {
    if (!to) return;
    const tick = () => setLeft(Math.max(0, Math.round((new Date(to).getTime() - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [to]);
  if (left === null) return null;
  return <span className={left < 30 ? "text-red-600" : ""}>⏱ {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</span>;
}

export function PlayerPanel({ matchId, over, battingTeam, onDone }: { matchId: number; over: OverView; battingTeam: string; onDone: () => void }) {
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const role = over.your_role;
  if (!role) return null;
  const mine = over.mine;
  const restricted = (role === "bat" && over.over_type === "bowling_pp") || (role === "bowl" && over.over_type === "batting_pp");

  async function submit(digits: number[]) {
    setBusy(true);
    setErr(null);
    try {
      await post(`/matches/${matchId}/overs/current/submit`, { digits });
      onDone();
    } catch (e) {
      const d = e instanceof ApiError ? e.message : "Could not submit";
      setErr(d);
    }
    setBusy(false);
  }

  return (
    <section className="space-y-3 rounded-lg border-2 border-foreground p-4">
      <div className="flex items-center justify-between">
        <p className="font-medium">Over {over.number} · you are the {role === "bat" ? "BATTER" : "BOWLER"} ({battingTeam} batting)</p>
        {over.state === "submissions_open" && <Countdown to={over.deadline_at} />}
      </div>
      <p className="text-sm text-muted-foreground">{overLabel(over.over_type)}</p>
      {over.state === "awaiting_signal" && <p className="text-sm">Wait for the umpire&apos;s signal…</p>}
      {over.state === "submissions_open" && !mine && (
        <>
          {restricted && <p className="text-sm font-medium">Use 5 and 6 exactly once each.</p>}
          {role === "bowl" && <p className="text-xs text-muted-foreground">One digit may repeat up to 3 times, every other digit at most 2.</p>}
          <DigitKeypad onConfirm={(d) => !busy && void submit(d)} />
          <ErrorText msg={err} />
        </>
      )}
      {over.state === "submissions_open" && mine && (
        <p className="text-sm">🔒 Locked: <span className="text-lg">{show(mine)}</span><br />Waiting for the umpire.</p>
      )}
      {over.state === "locked" && <p className="text-sm">🔒 {show(mine)} · umpire is about to reveal.</p>}
      {(over.state === "revealed" || over.state === "resolved") && over.digits && (
        <div className="text-sm">
          <p>Batter: {show(over.digits.bat)}</p>
          <p>Bowler: {show(over.digits.bowl)}</p>
        </div>
      )}
    </section>
  );
}
