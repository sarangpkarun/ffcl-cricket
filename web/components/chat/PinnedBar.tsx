"use client";

import { useState } from "react";
import type { ChatMsg } from "@/lib/api";

export function PinnedBar({ pinned }: { pinned: ChatMsg[] }) {
  const [open, setOpen] = useState(false);
  if (pinned.length === 0) return null;
  const top = pinned[0];
  return (
    <div className="border-b bg-muted/60 px-3 py-2 text-xs">
      <button type="button" aria-expanded={open} className="flex w-full items-center gap-2 text-left" onClick={() => setOpen((v) => !v)}>
        <span>📌</span>
        <span className="min-w-0 flex-1 truncate">{top.sender?.name}: {top.body}</span>
        {pinned.length > 1 && <span className="text-muted-foreground">{pinned.length} pinned {open ? "▴" : "▾"}</span>}
      </button>
      {open && (
        <ul className="mt-2 space-y-1">
          {pinned.map((p) => <li key={p.id} className="rounded border bg-background px-2 py-1"><b>{p.sender?.name}</b>: {p.body}</li>)}
        </ul>
      )}
    </div>
  );
}
