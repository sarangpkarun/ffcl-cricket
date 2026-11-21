const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Tokens = { access_token: string; refresh_token: string };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const KEY = "ffcl.tokens";

export function loadTokens(): Tokens | null {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Tokens) : null;
  } catch {
    return null;
  }
}

export function saveTokens(t: Tokens | null) {
  try {
    if (t) localStorage.setItem(KEY, JSON.stringify(t));
    else localStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: session lasts until reload */
  }
}

function detail(body: unknown): string {
  const d = (body as { detail?: unknown })?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e) => (e as { msg: string }).msg).join(", ");
  return "Request failed";
}

async function raw(path: string, init: RequestInit, token?: string) {
  return fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
}

let refreshing: Promise<Tokens | null> | null = null;

async function refresh(): Promise<Tokens | null> {
  const t = loadTokens();
  if (!t) return null;
  refreshing ??= raw("/auth/refresh", {
    method: "POST",
    body: JSON.stringify({ refresh_token: t.refresh_token }),
  })
    .then(async (r) => {
      if (!r.ok) {
        saveTokens(null);
        return null;
      }
      const next = (await r.json()) as Tokens;
      saveTokens(next);
      return next;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  let t = loadTokens();
  let res = await raw(path, init, t?.access_token);
  if (res.status === 401 && t) {
    t = await refresh();
    if (t) res = await raw(path, init, t.access_token);
  }
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, detail(body));
  return body as T;
}

export const post = <T,>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data === undefined ? undefined : JSON.stringify(data) });
export const put = <T,>(path: string, data: unknown) =>
  api<T>(path, { method: "PUT", body: JSON.stringify(data) });
export const patch = <T,>(path: string, data: unknown) =>
  api<T>(path, { method: "PATCH", body: JSON.stringify(data) });
export const del = <T,>(path: string) => api<T>(path, { method: "DELETE" });

export type Me = {
  id: number;
  player_code: string;
  name: string;
  email: string;
  phone: string | null;
  phone_verified: boolean;
  roles: string[];
  status: string;
};
export type Season = { id: number; name: string; status: string };
export type Team = {
  id: number;
  season_id: number;
  name: string;
  color: string | null;
  captain_id: number | null;
};
export type Member = { user_id: number; status: string; name: string | null; player_code: string | null };
export type TeamDetail = Team & { members: Member[] };
export type Match = {
  id: number;
  season_id: number;
  match_no: number;
  team_a_id: number;
  team_b_id: number;
  umpire_id: number | null;
  scheduled_at: string | null;
  status: string;
};
export type MatchDetail = Match & { lineup: { team_id: number; user_id: number }[] };
export type UserLite = { id: number; name: string; player_code: string };
