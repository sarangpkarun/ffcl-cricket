"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, put } from "@/lib/api";
import { useNotifications } from "@/lib/notifications";

type Pref = { kind: string; label: string; in_app: boolean };
const ago = (iso: string) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function Inbox() {
  const { items, unread, hasMore, markRead, markAll, loadMore } = useNotifications();
  const router = useRouter();
  const [prefs, setPrefs] = useState<Pref[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api<Pref[]>("/notifications/prefs").then(setPrefs).catch((e) => setErr(e.message));
  }, []);

  async function toggle(p: Pref) {
    setErr(null);
    setPrefs((cur) => cur.map((x) => (x.kind === p.kind ? { ...x, in_app: !p.in_app } : x)));
    try {
      await put("/notifications/prefs", { kind: p.kind, in_app: !p.in_app });
    } catch (e) {
      setErr((e as Error).message);
      setPrefs((cur) => cur.map((x) => (x.kind === p.kind ? { ...x, in_app: p.in_app } : x)));
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Notifications</h1>
        <button className={btnGhost} disabled={unread === 0} onClick={() => void markAll()}>Mark all read</button>
      </div>
      <ErrorText msg={err} />
      {items.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet. Match reminders, your turns and results will show up here.</p>}
      <ul className="space-y-2">
        {items.map((n) => (
          <li key={n.id}>
            <button
              type="button"
              className={`w-full rounded-lg border p-3 text-left ${n.read ? "" : "border-blue-500 bg-blue-50"}`}
              onClick={() => { void markRead(n.id); if (n.data.link) router.push(n.data.link); }}
            >
              <p className="text-sm font-medium">{!n.read && <span aria-label="unread">● </span>}{n.title}</p>
              {n.body && <p className="text-sm text-muted-foreground">{n.body}</p>}
              <p className="mt-1 text-[11px] text-muted-foreground">{ago(n.created_at)}</p>
            </button>
          </li>
        ))}
      </ul>
      {hasMore && <button className={btnGhost} onClick={() => void loadMore()}>Load older</button>}

      <section className="space-y-2">
        <h2 className="font-medium">Tell me when…</h2>
        <ul className="space-y-1">
          {prefs.map((p) => (
            <li key={p.kind}>
              <label className="flex items-center justify-between rounded-lg border px-3 py-3 text-sm">
                <span>{p.label}</span>
                <input type="checkbox" aria-label={p.label} checked={p.in_app} onChange={() => void toggle(p)} />
              </label>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Inbox /></RequireAuth>;
}
