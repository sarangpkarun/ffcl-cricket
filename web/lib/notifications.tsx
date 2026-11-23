"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, loadTokens, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS = API.replace(/^http/, "ws");

export type Notif = {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  data: { link?: string };
  created_at: string;
  read: boolean;
};
type Page = { notifications: Notif[]; has_more: boolean; unread: number };

type Ctx = {
  connected: boolean;
  items: Notif[];
  unread: number;
  hasMore: boolean;
  toast: Notif | null;
  dismissToast: () => void;
  markRead: (id: number) => Promise<void>;
  markAll: () => Promise<void>;
  loadMore: () => Promise<void>;
};
const NotifCtx = createContext<Ctx | null>(null);

/** One socket per signed-in user; the bell, the toast and the inbox all read from here. */
export function NotificationsProvider({ children }: { children: React.ReactNode }) {
  const { me } = useAuth();
  const [items, setItems] = useState<Notif[]>([]);
  const [unread, setUnread] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [toast, setToast] = useState<Notif | null>(null);
  const [connected, setConnected] = useState(false);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const userId = me?.id;

  const reload = useCallback(async () => {
    try {
      const p = await api<Page>("/notifications?limit=30");
      setItems(p.notifications);
      setHasMore(p.has_more);
      setUnread(p.unread);
    } catch {
      /* the bell is best effort */
    }
  }, []);

  useEffect(() => {
    if (!userId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when signing out
      setItems([]);
      setUnread(0);
      return;
    }
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ws: WebSocket | null = null;

    // Tell the server whether this page is in front, so it does not also push a notification to the phone
    // while the person is looking at the app.
    const tellServer = () => {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: document.visibilityState === "visible" ? "fg" : "bg" }));
    };
    const beat = setInterval(() => document.visibilityState === "visible" && tellServer(), 20_000);
    document.addEventListener("visibilitychange", tellServer);

    const connect = async () => {
      try {
        await api("/me"); // refresh an expired access token before the handshake
      } catch {
        /* ignored */
      }
      const tokens = loadTokens();
      if (closed || !tokens) return;
      ws = new WebSocket(`${WS}/ws/me`);
      ws.onopen = () => {
        ws?.send(JSON.stringify({ type: "auth", token: tokens.access_token }));
        tellServer();
      };
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data as string) as { type: string; unread?: number; notification?: Notif };
        if (ev.type === "hello") {
          retry = 0;
          setConnected(true);
          void reload(); // resync after any gap
        } else if (ev.type === "notification" && ev.notification) {
          const n = ev.notification;
          setItems((cur) => (cur.some((x) => x.id === n.id) ? cur : [n, ...cur]));
          setUnread((u) => u + 1);
          setToast(n);
          clearTimeout(toastTimer.current);
          toastTimer.current = setTimeout(() => setToast(null), 6000);
        }
      };
      ws.onclose = (e) => {
        setConnected(false);
        if (!closed && e.code !== 4401) timer = setTimeout(() => void connect(), Math.min(1000 * 2 ** retry++, 15_000));
      };
    };

    void reload();
    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearTimeout(toastTimer.current);
      clearInterval(beat);
      document.removeEventListener("visibilitychange", tellServer);
      ws?.close();
    };
  }, [userId, reload]);

  const markRead = useCallback(async (id: number) => {
    setItems((cur) => cur.map((n) => (n.id === id ? { ...n, read: true } : n)));
    setUnread((u) => Math.max(0, u - (items.find((n) => n.id === id && !n.read) ? 1 : 0)));
    try {
      await post(`/notifications/${id}/read`);
    } catch {
      void reload();
    }
  }, [items, reload]);

  const markAll = useCallback(async () => {
    setItems((cur) => cur.map((n) => ({ ...n, read: true })));
    setUnread(0);
    try {
      await post("/notifications/read-all");
    } catch {
      void reload();
    }
  }, [reload]);

  const loadMore = useCallback(async () => {
    const before = items[items.length - 1]?.id;
    if (!before) return;
    const p = await api<Page>(`/notifications?limit=30&before=${before}`);
    setItems((cur) => [...cur, ...p.notifications.filter((n) => !cur.some((x) => x.id === n.id))]);
    setHasMore(p.has_more);
  }, [items]);

  return (
    <NotifCtx.Provider value={{ connected, items, unread, hasMore, toast, dismissToast: () => setToast(null), markRead, markAll, loadMore }}>
      {children}
    </NotifCtx.Provider>
  );
}

export function useNotifications(): Ctx {
  const c = useContext(NotifCtx);
  if (!c) throw new Error("useNotifications outside NotificationsProvider");
  return c;
}
