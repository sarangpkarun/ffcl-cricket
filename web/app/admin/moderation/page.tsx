"use client";

import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, del, post } from "@/lib/api";

type Report = {
  message: { id: number; room_title: string | null; sender: { id: number; name: string } | null; body: string | null; deleted: boolean; created_at: string };
  reports: { id: number; reporter: string | null; reason: string }[];
  count: number;
};
type Mute = { id: number; user: { id: number; name: string }; until: string; reason: string };
type SeasonRoom = { room_id: number; title: string };

function Moderation() {
  const [reports, setReports] = useState<Report[]>([]);
  const [mutes, setMutes] = useState<Mute[]>([]);
  const [rooms, setRooms] = useState<SeasonRoom[]>([]);
  const [hours, setHours] = useState("24");
  const [room, setRoom] = useState("");
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, m, s] = await Promise.all([api<Report[]>("/admin/reports"), api<Mute[]>("/admin/mutes"), api<SeasonRoom[]>("/chat/home")]);
      setReports(r);
      setMutes(m);
      setRooms(s);
      setRoom((cur) => cur || String(s[0]?.room_id ?? ""));
    } catch (e) { setErr((e as Error).message); }
  }, []);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
  useEffect(() => { void load(); }, [load]);

  const act = async (fn: () => Promise<unknown>, done?: string) => {
    setErr(null);
    setOk(null);
    try { await fn(); if (done) setOk(done); await load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-primary">Chat moderation</h1>
      <ErrorText msg={err} />
      {ok && <p role="status" className="text-sm text-success">{ok}</p>}

      <section className="space-y-3">
        <h2 className="font-medium">Reported messages ({reports.length})</h2>
        {reports.length === 0 && <p className="text-sm text-muted-foreground">Nothing waiting. 🎉</p>}
        {reports.map((r) => (
          <article key={r.message.id} className="space-y-2 card-elevated rounded-2xl border bg-card p-3">
            <p className="text-xs text-muted-foreground">{r.message.room_title} · {r.message.sender?.name} · {new Date(r.message.created_at).toLocaleString()}</p>
            <p className="whitespace-pre-wrap break-words text-sm">{r.message.body ?? "(no text)"}{r.message.deleted && " — already removed"}</p>
            <ul className="text-xs text-muted-foreground">
              {r.reports.map((x) => <li key={x.id}>⚑ {x.reporter}: {x.reason}</li>)}
            </ul>
            <div className="flex flex-wrap items-center gap-2">
              <button className={btnGhost} onClick={() => act(() => post(`/admin/reports/${r.reports[0].id}/resolve`, { action: "dismiss" }), "Dismissed.")}>Dismiss</button>
              <button className={btnGhost} onClick={() => act(() => post(`/admin/reports/${r.reports[0].id}/resolve`, { action: "delete" }), "Message removed.")}>Delete message</button>
              <span className="flex items-center gap-1">
                <select aria-label="Mute length" className="rounded border bg-background px-2 py-2 text-sm" value={hours} onChange={(e) => setHours(e.target.value)}>
                  <option value="1">1 h</option><option value="24">24 h</option><option value="168">7 days</option><option value="720">30 days</option>
                </select>
                <button className={btnGhost} onClick={() => act(() => post(`/admin/reports/${r.reports[0].id}/resolve`, { action: "delete_and_mute", mute_hours: Number(hours) }), `Removed and muted ${r.message.sender?.name}.`)}>Delete + mute</button>
              </span>
            </div>
          </article>
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">Active mutes ({mutes.length})</h2>
        {mutes.length === 0 && <p className="text-sm text-muted-foreground">Nobody is muted.</p>}
        {mutes.map((m) => (
          <div key={m.id} className="flex items-center justify-between card-elevated rounded-2xl border bg-card p-3 text-sm">
            <span>{m.user.name}<br /><span className="text-xs text-muted-foreground">until {new Date(m.until).toLocaleString()} · {m.reason}</span></span>
            <button className={btnGhost} onClick={() => act(() => del(`/admin/mutes/${m.id}`), `Lifted mute for ${m.user.name}.`)}>Lift</button>
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="font-medium">📢 Announcement</h2>
        <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); void act(async () => { await post(`/rooms/${room}/announcements`, { body: text }); setText(""); }, "Announcement posted and pinned."); }}>
          <select aria-label="Season chat" className={inputCls} value={room} onChange={(e) => setRoom(e.target.value)}>
            {rooms.map((s) => <option key={s.room_id} value={s.room_id}>{s.title}</option>)}
          </select>
          <textarea aria-label="Announcement text" className={inputCls} rows={3} maxLength={2000} required placeholder="Visible to everyone in the season chat" value={text} onChange={(e) => setText(e.target.value)} />
          <button className={btnCls} disabled={!room || !text.trim()}>Post announcement</button>
        </form>
      </section>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin global><Moderation /></RequireAuth>;
}
