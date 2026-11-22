"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, del, loadTokens, patch, post, type ChatMsg, type Pending, type Person } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS = API.replace(/^http/, "ws");
const HEARTBEAT_MS = 20_000;
const TYPING_SHOW_MS = 4_000;
const TYPING_SEND_MS = 2_000;
type Page = { messages: ChatMsg[]; has_more: boolean };
export type SendOpts = { replyToId?: number; mentions?: number[] };

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
export function useRoom(roomId: number, myId: number) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [pending, setPending] = useState<Pending[]>([]);
  const [pinned, setPinned] = useState<ChatMsg[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [online, setOnline] = useState<Person[]>([]);
  const [typing, setTyping] = useState<Person[]>([]);
  const [reads, setReads] = useState<Record<number, { name: string; last: number }>>({});
  const [connected, setConnected] = useState(false);
  const [stateTick, setStateTick] = useState(0); // bumps when the room's rules change (e.g. the submission chat lock)
  const [error, setError] = useState<string | null>(null);
  const last = useRef(0);
  const presenceVersion = useRef(0); // bumps on every live presence event
  const sentRead = useRef(0);
  const lastTypingSent = useRef(0);
  const socket = useRef<WebSocket | null>(null);
  const typingTimers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());
  const sendFor = useRef<(p: Pending) => Promise<void>>(async () => {});

  const take = useCallback((incoming: ChatMsg[]) => {
    if (!incoming.length) return;
    setMessages((cur) => incoming.reduce(upsert, cur));
    setPending((cur) => cur.filter((p) => !incoming.some((m) => m.client_id === p.client_id)));
    last.current = Math.max(last.current, ...incoming.map((m) => m.id));
  }, []);

  const applyPin = useCallback((m: ChatMsg) => {
    setPinned((cur) => {
      const rest = cur.filter((x) => x.id !== m.id);
      return m.pinned && !m.deleted ? [m, ...rest].slice(0, 5) : rest;
    });
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
      setPinned(await api<ChatMsg[]>(`/rooms/${roomId}/pinned`));
      const rs = await api<{ user_id: number; name: string; last_read_id: number }[]>(`/rooms/${roomId}/reads`);
      setReads(Object.fromEntries(rs.map((r) => [r.user_id, { name: r.name, last: r.last_read_id }])));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [roomId, take]);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let beat: ReturnType<typeof setInterval> | undefined;
    const timers = typingTimers.current;

    const connect = async () => {
      try {
        await api("/me"); // refreshes an expired access token before the socket handshake
      } catch {
        /* handled by sync() */
      }
      const tokens = loadTokens();
      if (closed || !tokens) return;
      const ws = new WebSocket(`${WS}/ws/rooms/${roomId}`);
      socket.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token: tokens.access_token }));
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
            if ((ev.message as ChatMsg).kind === "announcement") applyPin(ev.message as ChatMsg);
            break;
          case "room_state":
            setStateTick((t) => t + 1);
            break;
          case "pinned":
            take([ev.message as ChatMsg]);
            applyPin(ev.message as ChatMsg);
            break;
          case "reaction":
            setMessages((cur) => cur.map((m) => (m.id === ev.message_id ? { ...m, reactions: ev.reactions as ChatMsg["reactions"] } : m)));
            break;
          case "deleted":
            setMessages((cur) => cur.map((m) => (m.id === ev.id ? { ...m, body: null, meta: null, reactions: {}, reply_to: null, pinned: false, deleted: true } : m)));
            setPinned((cur) => cur.filter((m) => m.id !== ev.id));
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
          case "typing": {
            const u = ev.user as Person;
            if (u.id === myId) break;
            setTyping((cur) => [...cur.filter((x) => x.id !== u.id), u]);
            clearTimeout(timers.get(u.id));
            timers.set(u.id, setTimeout(() => setTyping((cur) => cur.filter((x) => x.id !== u.id)), TYPING_SHOW_MS));
            break;
          }
          case "read": {
            const u = ev.user as Person;
            setReads((cur) => ({ ...cur, [u.id]: { name: u.name, last: ev.last_id as number } }));
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
      beat = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send('{"type":"ping"}'), HEARTBEAT_MS);
    };

    void sync();
    void connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(beat);
      timers.forEach(clearTimeout);
      socket.current?.close();
    };
  }, [roomId, myId, sync, refreshOnline, take, applyPin]);

  sendFor.current = async (p: Pending) => {
    try {
      take([await post<ChatMsg>(`/rooms/${roomId}/messages`, {
        body: p.body, client_id: p.client_id, reply_to_id: p.replyToId ?? null, mentions: p.mentions ?? [],
      })]);
    } catch (e) {
      setPending((cur) => cur.map((x) => (x.client_id === p.client_id ? { ...x, failed: true, error: (e as Error).message } : x)));
    }
  };

  const send = useCallback((body: string, opts: SendOpts = {}) => {
    const p: Pending = { client_id: crypto.randomUUID().replaceAll("-", ""), body, failed: false, ...opts };
    setPending((cur) => [...cur, p]);
    void sendFor.current(p);
  }, []);

  const retrySend = useCallback((clientId: string) => {
    const p = pending.find((x) => x.client_id === clientId);
    if (!p) return;
    setPending((cur) => cur.map((x) => (x.client_id === clientId ? { ...x, failed: false, error: undefined } : x)));
    void sendFor.current({ ...p, failed: false });
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
    setMessages((cur) => cur.map((m) => (m.id === id ? { ...m, body: null, meta: null, reactions: {}, deleted: true } : m)));
    setPinned((cur) => cur.filter((m) => m.id !== id));
  }, [roomId]);

  const react = useCallback(async (id: number, emoji: string) => {
    const r = await post<{ reactions: ChatMsg["reactions"] }>(`/rooms/${roomId}/messages/${id}/reactions`, { emoji });
    setMessages((cur) => cur.map((m) => (m.id === id ? { ...m, reactions: r.reactions } : m)));
  }, [roomId]);

  const setPin = useCallback(async (id: number, on: boolean) => {
    const m = on ? await post<ChatMsg>(`/rooms/${roomId}/messages/${id}/pin`) : await del<ChatMsg>(`/rooms/${roomId}/messages/${id}/pin`).then(() => null);
    setMessages((cur) => cur.map((x) => (x.id === id ? { ...x, pinned: on } : x)));
    if (m) applyPin(m);
    else setPinned((cur) => cur.filter((x) => x.id !== id));
  }, [roomId, applyPin]);

  const report = useCallback((id: number, reason: string) => post(`/rooms/${roomId}/messages/${id}/report`, { reason }), [roomId]);

  const announce = useCallback(async (body: string) => {
    take([await post<ChatMsg>(`/rooms/${roomId}/announcements`, { body })]);
  }, [roomId, take]);

  /** Tell the room I'm typing (at most once per 2 seconds). */
  const sendTyping = useCallback(() => {
    const now = Date.now();
    const ws = socket.current;
    if (now - lastTypingSent.current < TYPING_SEND_MS || ws?.readyState !== WebSocket.OPEN) return;
    lastTypingSent.current = now;
    ws.send('{"type":"typing"}');
  }, []);

  /** Report the newest message I have actually seen (forward only). */
  const markRead = useCallback((lastId: number) => {
    if (lastId <= sentRead.current) return;
    sentRead.current = lastId;
    const ws = socket.current;
    if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "read", last_id: lastId }));
    else void post(`/rooms/${roomId}/read`, { last_id: lastId }).catch(() => {});
  }, [roomId]);

  return {
    messages, pending, pinned, hasMore, online, typing, reads, connected, error, stateTick,
    send, retrySend, discard, loadOlder, edit, remove, react, setPin, report, announce, sendTyping, markRead,
  };
}
