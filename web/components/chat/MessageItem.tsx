"use client";

import { useState } from "react";
import type { ChatMsg } from "@/lib/api";

const MAX = 2000;
const time = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Plain-text body with @mentions emphasised. Built from React nodes, never HTML. */
function Body({ m }: { m: ChatMsg }) {
  const names = (m.meta?.mentions ?? []).map((x) => x.name);
  if (!names.length || !m.body) return <>{m.body}</>;
  const parts = m.body.split(new RegExp(`(@(?:${names.map(esc).join("|")}))`, "g"));
  return <>{parts.map((p, i) => (p.startsWith("@") && names.includes(p.slice(1)) ? <b key={i} className="text-blue-700">{p}</b> : <span key={i}>{p}</span>))}</>;
}

export type Actions = {
  onReply: () => void;
  onReact: (emoji: string) => Promise<void>;
  onEdit: (body: string) => Promise<void>;
  onDelete: () => Promise<void>;
  onPin: (on: boolean) => Promise<void>;
  onReport: (reason: string) => Promise<unknown>;
};

export function MessageItem({ m, myId, canEdit, moderator, reactionSet, open, onToggle, seenBy, actions }: {
  m: ChatMsg; myId: number; canEdit: boolean; moderator: boolean; reactionSet: string[];
  open: boolean; onToggle: () => void; seenBy: string[]; actions: Actions;
}) {
  const mine = m.sender?.id === myId;
  const mentioned = !mine && !!m.meta?.mentions?.some((x) => x.id === myId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(m.body ?? "");
  const [reporting, setReporting] = useState(false);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState<string | null>(null);

  const guard = async (fn: () => Promise<unknown>) => {
    setNote(null);
    try { await fn(); } catch (x) { setNote((x as Error).message); }
  };

  if (m.kind === "announcement") {
    return (
      <li className="my-1">
        <div className="rounded-lg bg-foreground px-3 py-2 text-background">
          <p className="text-[11px] opacity-80">📢 Announcement · {m.sender?.name} · {time(m.created_at)}</p>
          <p className="whitespace-pre-wrap break-words text-sm">{m.deleted ? "Message removed" : m.body}</p>
          {moderator && !m.deleted && <button className="mt-1 text-[11px] underline" onClick={() => void guard(actions.onDelete)}>Delete</button>}
        </div>
      </li>
    );
  }
  if (m.kind === "system") {
    return (
      <li className="my-1 flex justify-center">
        <p className="max-w-[90%] rounded-full bg-muted px-3 py-1 text-center text-xs text-muted-foreground">{m.deleted ? "Message removed" : m.body}</p>
      </li>
    );
  }

  const chips = Object.entries(m.reactions).filter(([, ids]) => ids.length > 0);
  return (
    <li className={`flex flex-col ${mine ? "items-end" : "items-start"}`}>
      <div className={`max-w-[85%] rounded-lg border px-3 py-2 ${mine ? "bg-muted" : ""} ${mentioned ? "border-blue-500 ring-1 ring-blue-300" : ""}`}>
        {!mine && <p className="text-xs font-medium">{m.sender?.name}</p>}
        {m.reply_to && !m.deleted && (
          <p className="mb-1 rounded border-l-2 border-foreground/40 bg-background/60 px-2 py-1 text-xs text-muted-foreground">
            <b>{m.reply_to.sender_name ?? "Someone"}</b>: {m.reply_to.deleted ? "Message removed" : m.reply_to.snippet}
          </p>
        )}
        {m.deleted ? (
          <p className="text-sm italic text-muted-foreground">Message removed</p>
        ) : editing ? (
          <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); await guard(async () => { await actions.onEdit(draft); setEditing(false); }); }}>
            <textarea className="w-full rounded border bg-background p-2 text-sm" maxLength={MAX} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="flex gap-2 text-xs">
              <button className="rounded border px-2 py-1">Save</button>
              <button type="button" className="rounded border px-2 py-1" onClick={() => setEditing(false)}>Cancel</button>
            </div>
          </form>
        ) : (
          <button type="button" aria-label="Message options" aria-expanded={open} onClick={onToggle} className="block w-full whitespace-pre-wrap break-words text-left text-sm">
            <Body m={m} />
          </button>
        )}
        <p className="mt-1 text-[11px] text-muted-foreground">
          {time(m.created_at)}{m.edited_at && !m.deleted && " · edited"}{m.pinned && " · 📌"}
        </p>
      </div>

      {chips.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {chips.map(([emoji, ids]) => (
            <button key={emoji} aria-label={`${emoji} ${ids.length}`} onClick={() => void guard(() => actions.onReact(emoji))}
              className={`rounded-full border px-2 py-0.5 text-xs ${ids.includes(myId) ? "border-blue-500 bg-blue-50" : ""}`}>
              {emoji} {ids.length}
            </button>
          ))}
        </div>
      )}

      {open && !m.deleted && !editing && (
        <div className="mt-1 max-w-[95%] space-y-2 rounded-lg border bg-background p-2 text-xs shadow-sm">
          <div className="flex flex-wrap gap-1" role="group" aria-label="React">
            {reactionSet.map((e) => (
              <button key={e} className="rounded border px-2 py-1 text-base" aria-label={`React ${e}`} onClick={() => void guard(async () => { await actions.onReact(e); onToggle(); })}>{e}</button>
            ))}
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="rounded border px-2 py-1" onClick={() => { actions.onReply(); onToggle(); }}>Reply</button>
            {mine && canEdit && <button className="rounded border px-2 py-1" onClick={() => { setDraft(m.body ?? ""); setEditing(true); onToggle(); }}>Edit</button>}
            {(mine || moderator) && <button className="rounded border px-2 py-1" onClick={() => void guard(async () => { await actions.onDelete(); onToggle(); })}>Delete</button>}
            {moderator && <button className="rounded border px-2 py-1" onClick={() => void guard(async () => { await actions.onPin(!m.pinned); onToggle(); })}>{m.pinned ? "Unpin" : "Pin"}</button>}
            {!mine && <button className="rounded border px-2 py-1" onClick={() => setReporting((v) => !v)}>Report</button>}
          </div>
          {reporting && (
            <form className="flex gap-2" onSubmit={async (e) => {
              e.preventDefault();
              await guard(async () => { await actions.onReport(reason); setReporting(false); setReason(""); setNote("Reported. Thank you."); });
            }}>
              <input aria-label="Report reason" className="min-w-0 flex-1 rounded border bg-background px-2 py-1" minLength={3} required placeholder="What is wrong?" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="rounded border px-2 py-1">Send</button>
            </form>
          )}
        </div>
      )}
      {note && <p role="status" className="mt-1 text-[11px] text-muted-foreground">{note}</p>}
      {mine && seenBy.length > 0 && (
        <p className="mt-0.5 text-[11px] text-muted-foreground">Seen by {seenBy.slice(0, 3).join(", ")}{seenBy.length > 3 ? ` +${seenBy.length - 3}` : ""}</p>
      )}
    </li>
  );
}
