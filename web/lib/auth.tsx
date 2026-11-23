"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiError, api, loadTokens, post, saveTokens, type Me, type Tokens } from "@/lib/api";

type Ctx = {
  me: Me | null;
  loading: boolean;
  unreachable: boolean; // the server could not be reached; the sign-in is kept and we keep trying
  isAdmin: boolean; // an admin of something (everything, or some seasons): shows the admin screens
  isGlobalAdmin: boolean;
  adminScope: { is_global: boolean; seasons: number[] };
  canAdmin: (seasonId: number | null | undefined) => boolean; // an admin of this particular season
  login: (email: string, password: string) => Promise<void>;
  register: (d: { name: string; email: string; password: string; phone?: string }) => Promise<void>;
  acceptInvite: (token: string, email: string, password: string) => Promise<void>;
  logout: (all?: boolean) => Promise<void>;
  reload: () => Promise<void>;
};

const AuthCtx = createContext<Ctx | null>(null);
const NO_SCOPE = { is_global: false, seasons: [] as number[] }; // one shared object, so effects that depend on it do not re-run

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [unreachable, setUnreachable] = useState(false);

  const reload = useCallback(async () => {
    if (!loadTokens()) {
      setMe(null);
      setUnreachable(false);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/me"));
      setUnreachable(false);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
        saveTokens(null); // the server says this sign-in is over (expired, signed out elsewhere, suspended)
        setMe(null);
        setUnreachable(false);
      } else {
        // A network blip, a navigation that cancelled the request, a server hiccup: none of these end a session.
        setUnreachable(true);
      }
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    if (!unreachable) return;
    const retry = () => void reload();
    const t = setTimeout(retry, 3000);
    window.addEventListener("online", retry);
    return () => {
      clearTimeout(t);
      window.removeEventListener("online", retry);
    };
  }, [unreachable, reload]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial session restore from storage
    void reload();
  }, [reload]);

  const startSession = async (t: Tokens) => {
    saveTokens(t);
    await reload();
  };

  const value: Ctx = {
    me,
    loading,
    unreachable,
    isAdmin: !!me && (me.admin.is_global || me.admin.seasons.length > 0),
    isGlobalAdmin: !!me?.admin.is_global,
    adminScope: me?.admin ?? NO_SCOPE,
    canAdmin: (seasonId) => !!me && (me.admin.is_global || (seasonId != null && me.admin.seasons.includes(seasonId))),
    reload,
    login: async (email, password) => startSession(await post<Tokens>("/auth/login", { email, password })),
    register: async (d) => startSession(await post<Tokens>("/auth/register", d)),
    acceptInvite: async (token, email, password) => startSession(await post<Tokens>(`/invites/${encodeURIComponent(token)}/accept`, { email, password })),
    logout: async (all) => {
      const t = loadTokens();
      try {
        if (all) await post("/auth/logout-all");
        else if (t) await post("/auth/logout", { refresh_token: t.refresh_token });
      } catch {
        /* already logged out server-side */
      }
      saveTokens(null);
      setMe(null);
    },
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthCtx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
