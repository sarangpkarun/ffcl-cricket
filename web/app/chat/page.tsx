"use client";

import { useEffect, useState } from "react";
import { ChatRoom } from "@/components/chat/ChatRoom";
import { inputCls, RequireAuth } from "@/components/ui-bits";
import { api } from "@/lib/api";

type Home = { room_id: number; season_id: number; title: string };

function Chat() {
  const [rooms, setRooms] = useState<Home[] | null>(null);
  const [sel, setSel] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api<Home[]>("/chat/home")
      .then((r) => { setRooms(r); setSel(r[0]?.room_id ?? null); })
      .catch((e) => setErr(e.message));
  }, []);

  if (err) return <p role="alert" className="text-sm text-destructive">{err}</p>;
  if (!rooms) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (rooms.length === 0)
    return <p className="text-sm text-muted-foreground">You are not part of a season yet. Once a captain or admin adds you to a team, the league chat appears here.</p>;
  return (
    <div className="space-y-3">
      {rooms.length > 1 && (
        <select className={inputCls} value={sel ?? ""} onChange={(e) => setSel(Number(e.target.value))}>
          {rooms.map((r) => <option key={r.room_id} value={r.room_id}>{r.title}</option>)}
        </select>
      )}
      {sel && <ChatRoom key={sel} roomId={sel} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Chat /></RequireAuth>;
}
