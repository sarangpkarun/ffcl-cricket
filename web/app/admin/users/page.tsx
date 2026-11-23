"use client";

import { useCallback, useEffect, useState } from "react";
import { btnGhost, ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, del, post, put, type Season } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { VerifyPhone } from "@/components/admin/VerifyPhone";

type RoleRow = { role: string; season_id: number | null };
type AdminUser = {
  id: number; player_code: string; name: string; email: string; phone: string | null;
  phone_verified: boolean; phone_verified_by_admin: boolean; status: string; roles: RoleRow[];
};
type Page = { total: number; users: AdminUser[] };

const PAGE = 20;
const ADMIN_ROLES = ["super_admin", "tournament_admin"];
const GRANTABLE = ["player", "umpire", "tournament_admin", "super_admin"]; // captains are chosen on the team page
const label = (r: string) => r.replace("_", " ");

function Card({ u, canAdmin, isSuper, myId, seasons, onChange }: {
  u: AdminUser; canAdmin: boolean; isSuper: boolean; myId: number; seasons: Season[]; onChange: () => void;
}) {
  const [err, setErr] = useState<string | null>(null);
  const [role, setRole] = useState("umpire");
  const [season, setSeason] = useState(""); // for a season admin: which season
  const run = async (fn: () => Promise<unknown>) => {
    setErr(null);
    try { await fn(); onChange(); } catch (e) { setErr((e as Error).message); }
  };
  const mayRevoke = (r: string) => !ADMIN_ROLES.includes(r) || (isSuper && u.id !== myId);
  const options = GRANTABLE.filter((r) => isSuper || !ADMIN_ROLES.includes(r));

  return (
    <article className="space-y-2 rounded-lg border p-3" aria-label={`User ${u.name}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{u.name} <span className="text-xs text-muted-foreground">{u.player_code}</span></p>
          <p className="truncate text-xs text-muted-foreground">{u.email} · {u.phone ?? "no phone"} {u.phone && (u.phone_verified ? (u.phone_verified_by_admin ? "✅ verified by an admin" : "✅") : "⚠️ unverified")}</p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-xs ${u.status === "active" ? "" : "border-red-500 text-red-700"}`}>{u.status}</span>
      </div>

      <ul className="flex flex-wrap gap-1" aria-label="Roles">
        {u.roles.map((r) => (
          <li key={`${r.role}-${r.season_id}`} className="flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs">
            {label(r.role)}{r.season_id !== null && ` (${seasons.find((x) => x.id === r.season_id)?.name ?? `season ${r.season_id}`})`}
            {canAdmin && mayRevoke(r.role) && (
              <button type="button" aria-label={`Remove ${label(r.role)} from ${u.name}`}
                onClick={() => run(() => del(`/admin/users/${u.id}/roles/${r.role}${r.season_id !== null ? `?season_id=${r.season_id}` : ""}`))}>×</button>
            )}
          </li>
        ))}
      </ul>

      {canAdmin && u.phone && !u.phone_verified && u.id !== myId && <VerifyPhone u={u} onDone={onChange} />}
      {canAdmin && (
        <div className="flex flex-wrap items-center gap-2">
          <select aria-label={`Role to add for ${u.name}`} className="rounded border bg-background px-2 py-2 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
            {options.map((r) => <option key={r} value={r}>{label(r)}</option>)}
          </select>
          {role === "tournament_admin" && (
            <select aria-label={`Season for ${u.name}'s admin role`} className="rounded border bg-background px-2 py-2 text-sm" value={season} onChange={(e) => setSeason(e.target.value)}>
              <option value="">All seasons</option>
              {seasons.map((x) => <option key={x.id} value={x.id}>Only {x.name}</option>)}
            </select>
          )}
          <button className={btnGhost} onClick={() => run(() => post(`/users/${u.id}/roles`, { role, season_id: role === "tournament_admin" && season ? Number(season) : null }))}>Add role</button>
          {isSuper && u.id !== myId && (u.status === "active" ? (
            <>
              <button className={btnGhost} onClick={() => run(() => put(`/users/${u.id}/status`, { status: "suspended" }))}>Suspend</button>
              <button className={btnGhost} onClick={() => run(() => put(`/users/${u.id}/status`, { status: "banned" }))}>Ban</button>
            </>
          ) : (
            <button className={btnGhost} onClick={() => run(() => put(`/users/${u.id}/status`, { status: "active" }))}>Reactivate</button>
          ))}
        </div>
      )}
      <ErrorText msg={err} />
    </article>
  );
}

function People() {
  const { me, isAdmin } = useAuth();
  const [seasons, setSeasons] = useState<Season[]>([]);
  useEffect(() => { api<Season[]>("/seasons").then(setSeasons).catch(() => {}); }, []);
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<Page | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
    if (q.trim()) p.set("q", q.trim());
    if (role) p.set("role", role);
    if (status) p.set("status", status);
    try { setData(await api<Page>(`/admin/users?${p}`)); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [q, role, status, offset]);

  useEffect(() => {
    const t = setTimeout(() => void load(), 250); // wait for the typing to settle
    return () => clearTimeout(t);
  }, [load]);

  if (!me) return null;
  const isSuper = me.roles.includes("super_admin");
  const total = data?.total ?? 0;

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">People</h1>
      <input aria-label="Search people" className={inputCls} placeholder="Name, email, phone or player ID" value={q}
        onChange={(e) => { setQ(e.target.value); setOffset(0); }} />
      <div className="flex gap-2">
        <select aria-label="Filter by role" className={inputCls} value={role} onChange={(e) => { setRole(e.target.value); setOffset(0); }}>
          <option value="">Any role</option>
          {["player", "umpire", "captain", "tournament_admin", "super_admin"].map((r) => <option key={r} value={r}>{label(r)}</option>)}
        </select>
        <select aria-label="Filter by status" className={inputCls} value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0); }}>
          <option value="">Any status</option>
          <option value="active">Active</option><option value="suspended">Suspended</option><option value="banned">Banned</option>
        </select>
      </div>
      <ErrorText msg={err} />
      <p className="text-xs text-muted-foreground" aria-live="polite">{total} {total === 1 ? "person" : "people"}</p>
      <div className="space-y-3">
        {data?.users.map((u) => <Card key={u.id} u={u} canAdmin={isAdmin} isSuper={isSuper} seasons={seasons} myId={me.id} onChange={() => void load()} />)}
      </div>
      {total > PAGE && (
        <div className="flex items-center justify-between">
          <button className={btnGhost} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>Previous</button>
          <span className="text-xs text-muted-foreground">{offset + 1}–{Math.min(offset + PAGE, total)} of {total}</span>
          <button className={btnGhost} disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>Next</button>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin global><People /></RequireAuth>;
}
