"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Live } from "@/lib/api";

/** Polls the match read-model. Sprint 4 replaces polling with a WebSocket. */
export function useLive(matchId: string, everyMs = 2500) {
  const [live, setLive] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLive(await api<Live>(`/matches/${matchId}/live`));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [matchId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- fetch on mount
    void refresh();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") void refresh();
    }, everyMs);
    return () => clearInterval(t);
  }, [refresh, everyMs]);

  return { live, error, refresh };
}
