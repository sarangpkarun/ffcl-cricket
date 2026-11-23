"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Live } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS = API.replace(/^http/, "ws");
const POLL_MS = 8_000; // used whenever the socket is not connected
const SAFETY_MS = 30_000;

/**
 * Live match state for a signed-out visitor. The socket only says "changed, seq N"; the page then
 * refetches the public view. If the socket is unavailable (blocked, or too many from one address) it
 * simply polls, so the page stays current either way.
 */
export function usePublicLive(matchId: number, initial: Live) {
  const [live, setLive] = useState<Live>(initial);
  const [connected, setConnected] = useState(false);
  const seq = useRef(initial.match.seq);

  const refresh = useCallback(async () => {
    try {
      const res = await fetch(`${API}/public/matches/${matchId}/live`, { cache: "no-store" }); // the browser must not serve its own 2-second copy after a change event
      if (!res.ok) return;
      const next = (await res.json()) as Live;
      if (next.match.seq >= seq.current) {
        seq.current = next.match.seq;
        setLive(next);
      }
    } catch {
      /* offline: the next poll tries again */
    }
  }, [matchId]);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let isConnected = false;

    const connect = () => {
      ws = new WebSocket(`${WS}/ws/public/matches/${matchId}`);
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data as string) as { type: string; seq?: number };
        if (m.type === "hello") {
          retry = 0;
          isConnected = true;
          setConnected(true);
          void refresh();
        } else if (m.type === "changed" && (m.seq ?? 0) > seq.current) void refresh();
      };
      ws.onclose = (e) => {
        isConnected = false;
        setConnected(false);
        if (!closed && e.code !== 4404 && e.code !== 4429) timer = setTimeout(connect, Math.min(1000 * 2 ** retry++, 15_000));
      };
    };

    connect();
    const poll = setInterval(() => document.visibilityState === "visible" && !isConnected && void refresh(), POLL_MS);
    const safety = setInterval(() => document.visibilityState === "visible" && void refresh(), SAFETY_MS);
    const onVisible = () => document.visibilityState === "visible" && void refresh();
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      closed = true;
      clearTimeout(timer);
      clearInterval(poll);
      clearInterval(safety);
      document.removeEventListener("visibilitychange", onVisible);
      ws?.close();
    };
  }, [matchId, refresh]);

  return { live, connected };
}
