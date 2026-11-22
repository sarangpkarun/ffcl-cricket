"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type ChatMsg, type RoomInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useRoom } from "@/lib/useRoom";

const EDIT_MS = 15 * 60 * 1000;
const MAX = 2000;
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

function Bubble({ m, mine, canEdit, moderator, onEdit, onDelete }: {
  m: ChatMsg; mine: boolean; canEdit: boolean; moderator: boolean;
  onEdit: (body: string) => Promise<void>; onDelete: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(m.body ?? "");
  const [err, setErr] = useState<string | null>(null);

  if (m.kind !== "user") {
    return (
      <li className="my-1 flex justify-center">
        <p className={`max-w-[90%] rounded-full px-3 py-1 text-center text-xs ${m.kind === "announcement" ? "bg-foreground text-background" : "bg-muted text-muted-foreground"}`}>
          {m.deleted ? "Message removed" : m.body}
        </p>
      </li>
    );
  }
  return (
    <li className={`flex ${mine ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] rounded-lg border px-3 py-2 ${mine ? "bg-muted" : ""}`}>
        {!mine && <p className="text-xs font-medium">{m.sender?.name}</p>}
        {m.deleted ? (
          <p className="text-sm italic text-muted-foreground">Message removed</p>
        ) : editing ? (
          <form className="space-y-2" onSubmit={async (e) => {
            e.preventDefault();
            setErr(null);
            try { await onEdit(draft); setEditing(false); } catch (x) { setErr((x as Error).message); }
          }}>
            <textarea className="w-full rounded border bg-background p-2 text-sm" maxLength={MAX} value={draft} onChange={(e) => setDraft(e.target.value)} />
            {err && <p role="alert" className="text-xs text-red-600">{err}</p>}
            <div className="flex gap-2 text-xs">
              <button className="rounded border px-2 py-1">Save</button>
              <button type="button" className="rounded border px-2 py-1" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <p className="whitespace-pre-wrap break-words text-sm">{m.body}</p>
        )}
        <p className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
          {time(m.created_at)}{m.edited_at && !m.deleted && " · edited"}
          {!m.deleted && !editing && (
            <>
              {mine && canEdit && <button className="underline" onClick={() => { setDraft(m.body ?? ""); setEditing(true); }}>Edit</button>}
              {(mine || moderator) && <button className="underline" onClick={() => void onDelete()}>Delete</button>}
            </>
          )}
        </p>
      </div>
    </li>
  );
}

/** Fill the screen below this element, above the bottom nav (and the phone keyboard). */
function useFillHeight(ref: React.RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const fit = () => {
      const el = ref.current;
      if (!el) return;
      const nav = document.querySelector("nav")?.getBoundingClientRect().height ?? 48;
      const viewport = window.visualViewport?.height ?? window.innerHeight;
      const top = el.getBoundingClientRect().top;
      el.style.height = `${Math.max(320, viewport - top - nav - 8)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    window.visualViewport?.addEventListener("resize", fit);
    return () => {
      window.removeEventListener("resize", fit);
      window.visualViewport?.removeEventListener("resize", fit);
    };
  }, [ref]);
}

export function ChatRoom({ roomId }: { roomId: number }) {
  const { me } = useAuth();
  const r = useRoom(roomId);
  const [info, setInfo] = useState<RoomInfo | null>(null);
  const [text, setText] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const list = useRef<HTMLUListElement>(null);
  const box = useRef<HTMLDivElement>(null);
  useFillHeight(box);
  const stick = useRef(true);

  useEffect(() => {
    api<RoomInfo>(`/rooms/${roomId}`).then(setInfo).catch(() => setInfo(null));
  }, [roomId]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000); // re-evaluate the 15-minute edit window
    return () => clearInterval(t);
  }, []);

  const count = r.messages.length + r.pending.length;
  useLayoutEffect(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [count]);

  if (!me) return null;
  const submit = () => {
    const body = text.trim();
    if (!body) return;
    r.send(body);
    setText("");
    stick.current = true;
  };

  return (
    <div ref={box} className="-mb-20 flex flex-col rounded-lg border" style={{ height: "60dvh" }}>
      <header className="flex items-center justify-between border-b px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">{info?.title ?? "Chat"}</h2>
          <p className="text-xs text-muted-foreground">
            {r.online.length} online{r.online.length > 0 && `: ${r.online.map((u) => u.name).slice(0, 3).join(", ")}${r.online.length > 3 ? "…" : ""}`}
          </p>
        </div>
        <span className={`text-xs ${r.connected ? "text-green-700" : "text-amber-700"}`} aria-live="polite">
          {r.connected ? "● Live" : "○ Reconnecting…"}
        </span>
      </header>

      <ul
        ref={list}
        className="flex-1 space-y-2 overflow-y-auto px-3 py-3"
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
        }}
      >
        {r.hasMore && (
          <li className="text-center">
            <button className="rounded border px-3 py-1 text-xs" onClick={() => { stick.current = false; void r.loadOlder(); }}>Load older messages</button>
          </li>
        )}
        {count === 0 && !r.error && <li className="py-8 text-center text-sm text-muted-foreground">No messages yet. Say hello 👋</li>}
        {r.messages.map((m) => (
          <Bubble key={m.id} m={m} mine={m.sender?.id === me.id}
            canEdit={now - new Date(m.created_at).getTime() < EDIT_MS}
            moderator={!!info?.moderator}
            onEdit={(b) => r.edit(m.id, b)} onDelete={() => r.remove(m.id)} />
        ))}
        {r.pending.map((p) => (
          <li key={p.client_id} className="flex justify-end">
            <div className="max-w-[85%] rounded-lg border border-dashed px-3 py-2 opacity-70">
              <p className="whitespace-pre-wrap break-words text-sm">{p.body}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {p.failed ? (
                  <>
                    <span className="text-red-600">Not sent{p.error ? `: ${p.error}` : ""}</span>{" "}
                    <button className="underline" onClick={() => r.retrySend(p.client_id)}>Retry</button>{" "}
                    <button className="underline" onClick={() => r.discard(p.client_id)}>Discard</button>
                  </>
                ) : "Sending…"}
              </p>
            </div>
          </li>
        ))}
      </ul>

      {r.error && <p role="alert" className="border-t px-3 py-1 text-xs text-red-600">{r.error}</p>}
      {info && !info.can_post ? (
        <p className="border-t px-3 py-3 text-center text-sm text-muted-foreground">You can read this chat but not post.</p>
      ) : (
        <form className="flex items-end gap-2 border-t p-2" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <textarea
            aria-label="Message"
            rows={1}
            maxLength={MAX}
            className="max-h-28 min-h-11 flex-1 resize-none rounded-md border bg-background px-3 py-2 text-base"
            placeholder="Type a message…"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
          />
          <button className="h-11 rounded-md bg-foreground px-4 text-background disabled:opacity-40" disabled={!text.trim()}>Send</button>
        </form>
      )}
    </div>
  );
}
