"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, loadTokens, type Live } from "@/lib/api";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS = API.replace(/^http/, "ws");
const SAFETY_POLL_MS = 15_000; // WebSocket is primary; this only covers a silently dead socket
const OFFLINE_POLL_MS = 3_000;

/**
 * Live match state. The socket only says "something changed (seq N)"; each client then
 * refetches its own privacy-filtered view, so no digits ever travel over the broadcast.
 * Every (re)connect refetches, so a missed message can never leave the screen stale.
 */
export function useLive(matchId: string) {
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const seq = useRef(-1);

  const refresh = useCallback(async () => {
    try {
      const next = await api<Live>(`/matches/${matchId}/live`);
      // responses can arrive out of order; never go backwards
      if (next.match.seq >= seq.current) {
        seq.current = next.match.seq;
        setLive(next);
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [matchId]);

  useEffect(() => {
    let closed = false;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let isConnected = false;

    const connect = async () => {
      try {
        await api("/me"); // refreshes an expired access token before we hand it to the socket
      } catch {
        /* surfaced by refresh() */
      }
      const tokens = loadTokens();
      if (closed || !tokens) return;
      ws = new WebSocket(`${WS}/ws/matches/${matchId}`);
      // the token goes in the first message, never the URL (URLs end up in access logs)
      ws.onopen = () => ws?.send(JSON.stringify({ type: "auth", token: tokens.access_token }));
      ws.onmessage = (e) => {
        const m = JSON.parse(e.data as string) as { type: string; seq?: number };
        if (m.type === "hello") {
          retry = 0;
          isConnected = true;
          setConnected(true);
          void refresh(); // resync after any gap
        } else if (m.type === "changed" && (m.seq ?? 0) > seq.current) void refresh();
      };
      ws.onclose = () => {
        isConnected = false;
        setConnected(false);
        if (!closed) timer = setTimeout(() => void connect(), Math.min(1000 * 2 ** retry++, 15_000));
      };
    };

    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void refresh();
    void connect();
    const poll = setInterval(() => {
      if (document.visibilityState !== "visible") return;
      if (!isConnected) void refresh();
    }, OFFLINE_POLL_MS);
    const safety = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, SAFETY_POLL_MS);
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

  return { live, error, refresh, connected };
}
