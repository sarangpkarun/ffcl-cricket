"use client";

import { useEffect, useState } from "react";
import { btnGhost, ErrorText } from "@/components/ui-bits";
import { post, type Live } from "@/lib/api";

/** The umpire's way out when a captain never answers the toss: unlocks after the scheduled start plus the rule's wait. */
export function TossAbsent({ live, onDone }: { live: Live; onDone: () => void }) {
  const { match, you } = live;
  const from = you.toss_absent_from ? new Date(you.toss_absent_from).getTime() : null;
  const [now, setNow] = useState(() => Date.now());
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (from === null) return;
    const t = setInterval(() => setNow(Date.now()), 15_000);
    return () => clearInterval(t);
  }, [from]);
  if (!you.official || from === null || (match.status !== "scheduled" && match.status !== "toss")) return null;
  const wait = Math.max(0, Math.ceil((from - now) / 60_000));

  return (
    <section className="space-y-2 card-elevated rounded-2xl border bg-card p-4" aria-label="Captain has not answered the toss">
      <h2 className="font-medium">A captain is not here?</h2>
      {wait > 0 ? (
        <p className="text-sm text-muted-foreground">The captains have {wait} more minute{wait === 1 ? "" : "s"} to answer the toss. After that you can award the match to the team that is here.</p>
      ) : (
        <>
          <p className="text-sm">The waiting time is over. Choose the team that did <b>not</b> answer; the other team is awarded the match. An admin can reverse this.</p>
          <div className="flex gap-3">
            {[match.team_a_id, match.team_b_id].map((t) => (
              <button key={t} className={`${btnGhost} flex-1`}
                onClick={async () => {
                  if (!window.confirm(`Award the match to the other team because ${match.teams[String(t)]} did not answer?`)) return;
                  setErr(null);
                  try { await post(`/matches/${match.id}/toss/absent`, { team_id: t }); onDone(); } catch (e) { setErr((e as Error).message); }
                }}>
                {match.teams[String(t)]} is absent
              </button>
            ))}
          </div>
        </>
      )}
      <ErrorText msg={err} />
    </section>
  );
}
