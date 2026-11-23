"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { btnGhost, ErrorText, RequireAuth } from "@/components/ui-bits";
import { api, post, put } from "@/lib/api";
import { disablePush, enablePush, pushState, type PushState } from "@/lib/push";
import { useNotifications } from "@/lib/notifications";

type Pref = { kind: string; label: string; in_app: boolean; push: boolean };
const ago = (iso: string) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

function PushSettings({ prefs, setPrefs }: { prefs: Pref[]; setPrefs: (f: (p: Pref[]) => Pref[]) => void }) {
  const [state, setState] = useState<PushState | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { void pushState().then(setState); }, []);
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setErr(null);
    setMsg(null);
    try { await fn(); if (done) setMsg(done); setState(await pushState()); } catch (e) { setErr((e as Error).message); }
  };
  async function toggle(p: Pref) {
    setPrefs((cur) => cur.map((x) => (x.kind === p.kind ? { ...x, push: !p.push } : x)));
    try { await put("/notifications/prefs", { kind: p.kind, push: !p.push }); }
    catch (e) { setErr((e as Error).message); setPrefs((cur) => cur.map((x) => (x.kind === p.kind ? { ...x, push: p.push } : x))); }
  }
  if (state === null || state === "disabled") return null;
  return (
    <section aria-label="Push notifications" className="space-y-2">
      <h2 className="font-medium">Alerts on this device</h2>
      <ErrorText msg={err} />
      {msg && <p role="status" className="text-sm text-green-700">{msg}</p>}
      {state === "unsupported" && <p className="text-sm text-muted-foreground">This browser cannot show alerts. On an iPhone, add FFCL to your Home Screen first, then open it from there.</p>}
      {state === "denied" && <p className="text-sm text-muted-foreground">Alerts are blocked for this site. Allow notifications in your browser&apos;s site settings, then come back.</p>}
      {state === "off" && <button className={btnGhost} onClick={() => run(enablePush, "Alerts are on for this device.")}>Turn on alerts on this device</button>}
      {state === "on" && (
        <div className="flex flex-wrap gap-2">
          <button className={btnGhost} onClick={() => run(() => post("/me/push/test"), "Test sent. You should see it in a moment.")}>Send a test alert</button>
          <button className={btnGhost} onClick={() => run(disablePush, "Alerts are off for this device.")}>Turn off on this device</button>
        </div>
      )}
      {state === "on" && (
        <>
          <p className="text-xs text-muted-foreground">Alerts are only sent when the app is not open in front of you. Choose which ones you want:</p>
          <ul className="space-y-1">
            {prefs.map((p) => (
              <li key={p.kind}>
                <label className="flex items-center justify-between rounded-lg border px-3 py-3 text-sm">
                  <span>{p.label}</span>
                  <input type="checkbox" aria-label={`Alert me: ${p.label}`} checked={p.push} onChange={() => void toggle(p)} />
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

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
              {n.body && <p className={`text-sm ${n.read ? "text-muted-foreground" : "text-foreground/80"}`}>{n.body}</p>}
              <p className={`mt-1 text-xs ${n.read ? "text-muted-foreground" : "text-foreground/80"}`}>{ago(n.created_at)}</p>
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
      <PushSettings prefs={prefs} setPrefs={setPrefs} />
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Inbox /></RequireAuth>;
}
