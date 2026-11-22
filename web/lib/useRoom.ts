"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, del, loadTokens, patch, post, type ChatMsg, type Pending } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS = API.replace(/^http/, "ws");
const HEARTBEAT_MS = 20_000;
type Person = { id: number; name: string };
type Page = { messages: ChatMsg[]; has_more: boolean };

/** Insert or replace by id, keeping ids ascending. */
function upsert(list: ChatMsg[], msg: ChatMsg): ChatMsg[] {
  const i = list.findIndex((m) => m.id === msg.id);
  if (i >= 0) {
    const next = list.slice();
    next[i] = msg;
    return next;
  }
  return [...list, msg].sort((a, b) => a.id - b.id);
}

/**
 * One chat room: history over REST, live events over a WebSocket.
 * Sends are optimistic and carry a client_id, so a retry can never create a duplicate.
 * Every (re)connect fetches whatever arrived after the newest message we hold.
 */
export function useRoom(roomId: number) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [online, setOnline] = useState<Person[]>([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);
  const presenceVersion = useRef(0); // bumps on every live presence event
  const sendFor = useRef<(p: Pending) => Promise<void>>(async () => {});

  const take = useCallback((incoming: ChatMsg[]) => {
    if (!incoming.length) return;
    setMessages((cur) => incoming.reduce(upsert, cur));
    setPending((cur) => cur.filter((p) => !incoming.some((m) => m.client_id === p.client_id)));
    last.current = Math.max(last.current, ...incoming.map((m) => m.id));
  }, []);

  const refreshOnline = useCallback(async () => {
    // A join/leave event that lands while this request is in flight makes the response stale,
    // so only apply it if nothing changed meanwhile; otherwise ask again.
    for (let attempt = 0; attempt < 3; attempt++) {
      const version = presenceVersion.current;
      try {
        const list = await api<Person[]>(`/rooms/${roomId}/online`);
        if (version === presenceVersion.current) {
          setOnline(list);
          return;
        }
      } catch {
        return; // presence is best effort
      }
    }
  }, [roomId]);

  const sync = useCallback(async () => {
    try {
      if (last.current === 0) {
        const p = await api<Page>(`/rooms/${roomId}/messages?limit=50`);
        setHasMore(p.has_more);
        take(p.messages);
      } else {
        for (;;) {
          const p = await api<Page>(`/rooms/${roomId}/messages?after=${last.current}&limit=200`);
          take(p.messages);
          if (!p.has_more) break;
        }
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [roomId, take]);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let beat: ReturnType<typeof setInterval> | undefined;

    const connect = async () => {
      try {
        await api("/me"); // refreshes an expired access token before the socket handshake
      } catch {
        /* handled by sync() */
      }
      const tokens = loadTokens();
      if (closed || !tokens) return;
      ws = new WebSocket(`${WS}/ws/rooms/${roomId}`);
      ws.onopen = () => ws?.send(JSON.stringify({ type: "auth", token: tokens.access_token }));
      ws.onmessage = (e) => {
        const ev = JSON.parse(e.data as string) as Record<string, unknown> & { type: string };
        switch (ev.type) {
          case "hello":
            retry = 0;
            setConnected(true);
            void sync();
            void refreshOnline();
            break;
          case "message":
          case "edited":
            take([ev.message as ChatMsg]);
            break;
          case "deleted":
            setMessages((cur) =>
              cur.map((m) => (m.id === ev.id ? { ...m, body: null, meta: null, deleted: true } : m)),
            );
            break;
          case "presence": {
            presenceVersion.current += 1;
            const u = ev.user as Person;
            setOnline((cur) => {
              const rest = cur.filter((x) => x.id !== u.id);
              return ev.online ? [...rest, u] : rest;
            });
            break;
          }
        }
      };
      ws.onclose = (e) => {
        setConnected(false);
        clearInterval(beat);
        if (e.code === 4403) setError("You no longer have access to this chat.");
        else if (!closed) timer = setTimeout(() => void connect(), Math.min(1000 * 2 ** retry++, 15_000));
      };
      beat = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send('{"type":"ping"}'), HEARTBEAT_MS);
    };

    void sync();
    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(beat);
      ws?.close();
    };
  }, [roomId, sync, refreshOnline, take]);

  sendFor.current = async (p: Pending) => {
    try {
      take([await post<ChatMsg>(`/rooms/${roomId}/messages`, { body: p.body, client_id: p.client_id })]);
    } catch (e) {
      setPending((cur) => cur.map((x) => (x.client_id === p.client_id ? { ...x, failed: true, error: (e as Error).message } : x)));
    }
  };

  const send = useCallback((body: string) => {
    const p: Pending = { client_id: crypto.randomUUID().replaceAll("-", ""), body, failed: false };
    setPending((cur) => [...cur, p]);
    void sendFor.current(p);
  }, []);

  const retrySend = useCallback((clientId: string) => {
    setPending((cur) => cur.map((x) => (x.client_id === clientId ? { ...x, failed: false, error: undefined } : x)));
    const p = pending.find((x) => x.client_id === clientId);
    if (p) void sendFor.current({ ...p, failed: false });
  }, [pending]);

  const discard = useCallback((clientId: string) => setPending((cur) => cur.filter((x) => x.client_id !== clientId)), []);

  const loadOlder = useCallback(async () => {
    const first = messages[0]?.id;
    if (!first) return;
    const p = await api<Page>(`/rooms/${roomId}/messages?before=${first}&limit=50`);
    setHasMore(p.has_more);
    setMessages((cur) => p.messages.reduce(upsert, cur));
  }, [roomId, messages]);

  const edit = useCallback(async (id: number, body: string) => {
    take([await patch<ChatMsg>(`/rooms/${roomId}/messages/${id}`, { body })]);
  }, [roomId, take]);

  const remove = useCallback(async (id: number) => {
    await del(`/rooms/${roomId}/messages/${id}`);
    setMessages((cur) => cur.map((m) => (m.id === id ? { ...m, body: null, meta: null, deleted: true } : m)));
  }, [roomId]);

  return { messages, pending, hasMore, online, connected, error, send, retrySend, discard, loadOlder, edit, remove };
}
