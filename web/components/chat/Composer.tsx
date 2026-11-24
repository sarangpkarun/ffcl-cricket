"use client";

import { useRef, useState } from "react";
import { api, type ChatMsg, type Mentionable } from "@/lib/api";

const MAX = 2000;

export function Composer({ roomId, moderator, replyTo, onCancelReply, onSend, onAnnounce, onTyping }: {
  roomId: number; moderator: boolean; replyTo: ChatMsg | null; onCancelReply: () => void;
  onSend: (body: string, mentions: number[]) => void; onAnnounce: (body: string) => Promise<void>; onTyping: () => void;
}) {
  const [text, setText] = useState("");
  const [picked, setPicked] = useState<Mentionable[]>([]);
  const [suggest, setSuggest] = useState<Mentionable[]>([]);
  const [announce, setAnnounce] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const seq = useRef(0);

  async function onChange(v: string) {
    setText(v);
    if (v) onTyping();
    const m = /(?:^|\s)@([^\s@]*)$/.exec(v);
    if (!m) return setSuggest([]);
    const mine = ++seq.current; // ignore out-of-order answers
    try {
      const rows = await api<Mentionable[]>(`/rooms/${roomId}/members?q=${encodeURIComponent(m[1])}`);
      if (mine === seq.current) setSuggest(rows.slice(0, 5));
    } catch {
      setSuggest([]);
    }
  }

  function pick(p: Mentionable) {
    setText((t) => t.replace(/@([^\s@]*)$/, `@${p.name} `));
    setPicked((cur) => (cur.some((x) => x.id === p.id) ? cur : [...cur, p]));
    setSuggest([]);
  }

  async function submit() {
    const body = text.trim();
    if (!body) return;
    setErr(null);
    if (announce) {
      try { await onAnnounce(body); setAnnounce(false); } catch (e) { setErr((e as Error).message); return; }
    } else {
      // only mention people whose @name is still in the text
      onSend(body, picked.filter((p) => body.includes(`@${p.name}`)).map((p) => p.id).slice(0, 10));
    }
    setText("");
    setPicked([]);
    setSuggest([]);
  }

  return (
    <div className="border-t p-2">
      {replyTo && (
        <div className="mb-2 flex items-start justify-between gap-2 rounded border-l-2 border-foreground/50 bg-muted px-2 py-1 text-xs">
          <p className="min-w-0 truncate">Replying to <b>{replyTo.sender?.name}</b>: {replyTo.body}</p>
          <button type="button" aria-label="Cancel reply" onClick={onCancelReply}>✕</button>
        </div>
      )}
      {suggest.length > 0 && (
        <ul className="mb-2 rounded border bg-background text-sm" role="listbox" aria-label="Mention someone">
          {suggest.map((s) => (
            <li key={s.id}>
              <button type="button" role="option" aria-selected={false} className="w-full px-3 py-2 text-left" onClick={() => pick(s)}>
                {s.name} <span className="text-xs text-muted-foreground">{s.player_code}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {err && <p role="alert" className="mb-1 text-xs text-destructive">{err}</p>}
      {moderator && (
        <label className="mb-1 flex items-center gap-2 text-xs">
          <input type="checkbox" checked={announce} onChange={(e) => setAnnounce(e.target.checked)} /> 📢 Send as pinned announcement
        </label>
      )}
      <form className="flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
        <textarea
          aria-label="Message"
          rows={1}
          maxLength={MAX}
          className="max-h-28 min-h-11 flex-1 resize-none rounded-md border bg-background px-3 py-2 text-base"
          placeholder={announce ? "Announcement…" : "Type a message… (@ to mention)"}
          value={text}
          onChange={(e) => void onChange(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void submit(); } }}
        />
        <button className="h-11 rounded-xl bg-primary px-4 text-primary-foreground disabled:opacity-40" disabled={!text.trim()}>{announce ? "Post" : "Send"}</button>
      </form>
    </div>
  );
}
