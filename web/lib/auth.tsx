"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, loadTokens, post, saveTokens, type Me, type Tokens } from "@/lib/api";

type Ctx = {
  me: Me | null;
  loading: boolean;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (d: { name: string; email: string; password: string; phone?: string }) => Promise<void>;
  logout: (all?: boolean) => Promise<void>;
  reload: () => Promise<void>;
};

const AuthCtx = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    if (!loadTokens()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/me"));
    } catch {
      saveTokens(null);
      setMe(null);
    }
    setLoading(false);
  }, []);

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
    isAdmin: !!me?.roles.some((r) => r === "super_admin" || r === "tournament_admin"),
    reload,
    login: async (email, password) => startSession(await post<Tokens>("/auth/login", { email, password })),
    register: async (d) => startSession(await post<Tokens>("/auth/register", d)),
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
