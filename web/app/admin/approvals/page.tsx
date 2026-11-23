"use client";

import { useCallback, useEffect, useState } from "react";
import { btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Person = { id: number; name: string; player_code: string } | null;
type Roster = { id: number; reason: string; team: { id: number; name: string }; out: Person; in: Person; requested_by: Person };
type Phone = { id: number; reason: string; user: { id: number; name: string; player_code: string }; current_phone: string | null; new_phone: string };

function Approvals() {
  const { isGlobalAdmin } = useAuth();
  const [roster, setRoster] = useState<Roster[]>([]);
  const [phones, setPhones] = useState<Phone[]>([]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRoster(await api<Roster[]>("/roster-changes?status=pending"));
      if (isGlobalAdmin) setPhones(await api<Phone[]>("/admin/phone-changes?status=pending")); // people's phone numbers are for global admins only
    } catch (e) { setErr((e as Error).message); }
  }, [isGlobalAdmin]);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void load(); }, [load]);

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setErr(null);
    setOk(null);
    try { await fn(); setOk(done); await load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold">Approvals</h1>
      <ErrorText msg={err} />
      {ok && <p role="status" className="text-sm text-green-700">{ok}</p>}

      <section aria-label="Roster changes" className="space-y-2">
        <h2 className="font-medium">Roster changes ({roster.length})</h2>
        {roster.length === 0 && <p className="text-sm text-muted-foreground">Nothing waiting.</p>}
        {roster.map((r) => {
          const key = `r${r.id}`;
          return (
            <article key={r.id} className="space-y-2 rounded-lg border p-3 text-sm">
              <p><b>{r.team.name}</b>: {r.out?.name} <span className="text-muted-foreground">out</span>, {r.in?.name} <span className="text-muted-foreground">in</span></p>
              <p className="text-xs text-muted-foreground">Asked by {r.requested_by?.name}: {r.reason}</p>
              <div className="flex gap-2">
                <input aria-label={`Note for roster change ${r.id}`} placeholder="Reason (needed to reject)" className="min-w-0 flex-1 rounded border bg-background px-2 py-2" value={notes[key] ?? ""} onChange={(e) => setNotes({ ...notes, [key]: e.target.value })} />
                <button className={btnGhost} onClick={() => act(() => post(`/roster-changes/${r.id}/approve`), "Roster change approved.")}>Approve</button>
                <button className={btnGhost} onClick={() => act(() => post(`/roster-changes/${r.id}/reject`, { note: notes[key] ?? "" }), "Roster change rejected.")}>Reject</button>
              </div>
            </article>
          );
        })}
      </section>

      {isGlobalAdmin && <section aria-label="Phone number changes" className="space-y-2">
        <h2 className="font-medium">Phone number changes ({phones.length})</h2>
        {phones.length === 0 && <p className="text-sm text-muted-foreground">Nothing waiting.</p>}
        {phones.map((p) => {
          const key = `p${p.id}`;
          return (
            <article key={p.id} className="space-y-2 rounded-lg border p-3 text-sm">
              <p><b>{p.user.name}</b> <span className="text-muted-foreground">{p.user.player_code}</span>: {p.current_phone} → <b>{p.new_phone}</b></p>
              <p className="text-xs text-muted-foreground">{p.reason}</p>
              <div className="flex gap-2">
                <input aria-label={`Note for phone change ${p.id}`} placeholder="Reason (needed to reject)" className="min-w-0 flex-1 rounded border bg-background px-2 py-2" value={notes[key] ?? ""} onChange={(e) => setNotes({ ...notes, [key]: e.target.value })} />
                <button className={btnGhost} onClick={() => act(() => post(`/admin/phone-changes/${p.id}/approve`), "Phone change approved. The player must confirm a code.")}>Approve</button>
                <button className={btnGhost} onClick={() => act(() => post(`/admin/phone-changes/${p.id}/reject`, { note: notes[key] ?? "" }), "Phone change rejected.")}>Reject</button>
              </div>
            </article>
          );
        })}
      </section>}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Approvals /></RequireAuth>;
}
