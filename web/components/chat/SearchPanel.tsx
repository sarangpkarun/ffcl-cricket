"use client";

import { useState } from "react";
import { api, type ChatMsg } from "@/lib/api";

type Hit = ChatMsg & { room: { id: number; title: string | null; kind: string } };

export function SearchPanel({ roomId, onClose }: { roomId: number; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const scope = all ? "" : `&room_id=${roomId}`;
      setHits(await api<Hit[]>(`/chat/search?q=${encodeURIComponent(q.trim())}${scope}`));
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  return (
    <div className="space-y-2 border-b bg-background p-3" role="search">
      <form className="flex gap-2" onSubmit={run}>
        <input aria-label="Search messages" className="min-w-0 flex-1 rounded border bg-background px-3 py-2 text-base" minLength={2} required placeholder="Search messages…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="rounded border px-3 py-2 text-sm">Search</button>
        <button type="button" className="rounded border px-3 py-2 text-sm" aria-label="Close search" onClick={onClose}>✕</button>
      </form>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> Search all my chats</label>
      {err && <p role="alert" className="text-xs text-destructive">{err}</p>}
      {hits && hits.length === 0 && <p className="text-xs text-muted-foreground">No messages found.</p>}
      {hits && hits.length > 0 && (
        <ul className="max-h-48 space-y-1 overflow-y-auto">
          {hits.map((h) => (
            <li key={h.id} className="rounded border px-2 py-1 text-xs">
              <p className="text-muted-foreground">{h.room.title} · {h.sender?.name} · {new Date(h.created_at).toLocaleString()}</p>
              <p className="whitespace-pre-wrap break-words text-sm">{h.body}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
