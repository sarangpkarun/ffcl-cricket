"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, type ChatMsg, type RoomInfo } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useRoom } from "@/lib/useRoom";
import { Composer } from "./Composer";
import { MessageItem } from "./MessageItem";
import { PinnedBar } from "./PinnedBar";
import { SearchPanel } from "./SearchPanel";

const EDIT_MS = 15 * 60 * 1000;

/** Fill the screen below this element, above the bottom nav (and the phone keyboard). */
function useFillHeight(ref: React.RefObject<HTMLElement | null>) {
  useLayoutEffect(() => {
    const fit = () => {
      const el = ref.current;
      if (!el) return;
      const nav = document.querySelector("nav")?.getBoundingClientRect().height ?? 48;
      const viewport = window.visualViewport?.height ?? window.innerHeight;
      el.style.height = `${Math.max(320, viewport - el.getBoundingClientRect().top - nav - 8)}px`;
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
  const r = useRoom(roomId, me?.id ?? 0);
  const [info, setInfo] = useState<RoomInfo | null>(null);
  const [reactionSet, setReactionSet] = useState<string[]>([]);
  const [now, setNow] = useState(() => Date.now());
  const [openId, setOpenId] = useState<number | null>(null);
  const [replyTo, setReplyTo] = useState<ChatMsg | null>(null);
  const [searching, setSearching] = useState(false);
  const list = useRef<HTMLUListElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useFillHeight(box);

  useEffect(() => {
    api<{ reactions: string[] }>("/chat/reactions").then((x) => setReactionSet(x.reactions)).catch(() => {});
  }, []);
  // Re-read the room's rules on load and whenever they change (the batter/bowler chat lock).
  useEffect(() => {
    api<RoomInfo>(`/rooms/${roomId}`).then(setInfo).catch(() => setInfo(null));
  }, [roomId, r.stateTick]);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000); // re-evaluate the 15-minute edit window
    return () => clearInterval(t);
  }, []);

  const count = r.messages.length + r.pending.length;
  useLayoutEffect(() => {
    const el = list.current;
    if (el && stick.current) el.scrollTop = el.scrollHeight;
  }, [count]);

  // Read receipts: only report what I can actually see (scrolled to the bottom, tab visible).
  const newest = r.messages[r.messages.length - 1]?.id ?? 0;
  const { markRead } = r;
  useEffect(() => {
    const report = () => {
      if (stick.current && document.visibilityState === "visible" && newest) markRead(newest);
    };
    report();
    document.addEventListener("visibilitychange", report);
    return () => document.removeEventListener("visibilitychange", report);
  }, [newest, markRead]);

  if (!me) return null;
  const myLast = [...r.messages].reverse().find((m) => m.sender?.id === me.id && !m.deleted)?.id ?? 0;
  const seenBy = Object.entries(r.reads).filter(([id, v]) => Number(id) !== me.id && v.last >= myLast).map(([, v]) => v.name);
  const typingNames = r.typing.map((t) => t.name);

  return (
    <div ref={box} className="-mb-20 flex flex-col rounded-lg border" style={{ height: "60dvh" }}>
      <header className="flex items-center justify-between border-b px-3 py-2">
        <div>
          <h2 className="text-sm font-semibold">{info?.title ?? "Chat"}</h2>
          <p className="text-xs text-muted-foreground">
            {r.online.length} online{r.online.length > 0 && `: ${r.online.map((u) => u.name).slice(0, 3).join(", ")}${r.online.length > 3 ? "…" : ""}`}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button type="button" aria-label="Search" className="text-lg" onClick={() => setSearching((v) => !v)}>🔍</button>
          <span className={`text-xs ${r.connected ? "text-success" : "text-warning"}`} aria-live="polite">
            {r.connected ? "● Live" : "○ Reconnecting…"}
          </span>
        </div>
      </header>

      {searching && <SearchPanel roomId={roomId} onClose={() => setSearching(false)} />}
      <PinnedBar pinned={r.pinned} />

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
          <MessageItem key={m.id} m={m} myId={me.id}
            canEdit={now - new Date(m.created_at).getTime() < EDIT_MS}
            moderator={!!info?.moderator} reactionSet={reactionSet}
            open={openId === m.id} onToggle={() => setOpenId((cur) => (cur === m.id ? null : m.id))}
            seenBy={m.id === myLast ? seenBy : []}
            actions={{
              onReply: () => setReplyTo(m),
              onReact: (e) => r.react(m.id, e),
              onEdit: (b) => r.edit(m.id, b),
              onDelete: () => r.remove(m.id),
              onPin: (on) => r.setPin(m.id, on),
              onReport: (reason) => r.report(m.id, reason),
            }} />
        ))}
        {r.pending.map((p) => (
          <li key={p.client_id} className="flex justify-end">
            <div className="max-w-[85%] rounded-lg border border-dashed px-3 py-2 opacity-70">
              <p className="whitespace-pre-wrap break-words text-sm">{p.body}</p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {p.failed ? (
                  <>
                    <span className="text-destructive">Not sent{p.error ? `: ${p.error}` : ""}</span>{" "}
                    <button className="underline" onClick={() => r.retrySend(p.client_id)}>Retry</button>{" "}
                    <button className="underline" onClick={() => r.discard(p.client_id)}>Discard</button>
                  </>
                ) : "Sending…"}
              </p>
            </div>
          </li>
        ))}
      </ul>

      <p className="h-4 px-3 text-[11px] text-muted-foreground" aria-live="polite">
        {typingNames.length > 0 && `${typingNames.slice(0, 2).join(" and ")} ${typingNames.length > 2 ? "and others are" : typingNames.length === 2 ? "are" : "is"} typing…`}
      </p>
      {r.error && <p role="alert" className="border-t px-3 py-1 text-xs text-destructive">{r.error}</p>}
      {info && !info.can_post ? (
        <p role="status" className="border-t px-3 py-3 text-center text-sm text-muted-foreground">{info.blocked_reason ?? "You can read this chat but not post."}</p>
      ) : (
        <Composer roomId={roomId} moderator={!!info?.moderator} replyTo={replyTo} onCancelReply={() => setReplyTo(null)}
          onSend={(body, mentions) => { r.send(body, { replyToId: replyTo?.id, mentions }); setReplyTo(null); stick.current = true; }}
          onAnnounce={r.announce} onTyping={r.sendTyping} />
      )}
    </div>
  );
}
