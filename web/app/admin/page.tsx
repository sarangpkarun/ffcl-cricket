"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, Field, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { adminSeasons } from "@/lib/seasons";

function Admin() {
  const { isGlobalAdmin, adminScope } = useAuth();
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [disputes, setDisputes] = useState<{ open: number; in_review: number } | null>(null);
  useEffect(() => { api<{ open: number; in_review: number }>("/admin/disputes/summary").then(setDisputes).catch(() => {}); }, []);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Season[]>("/seasons").then((all) => setSeasons(adminSeasons(all, adminScope))).catch((e) => setErr(e.message)), [adminScope]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-5">
      {isGlobalAdmin && <Link href="/admin/users" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">👥 People (roles, suspend)</Link>}
      {isGlobalAdmin && <Link href="/admin/moderation" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">🛡️ Chat moderation (reports, mutes, announcements)</Link>}
      <Link href="/admin/import" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">📥 Add players (import a list, invite links, verify numbers)</Link>
      <Link href="/admin/disputes" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">⚖️ Disputes{disputes && disputes.open + disputes.in_review > 0 && <span className="ml-2 rounded-full bg-destructive px-2 text-xs text-white" aria-label={`${disputes.open + disputes.in_review} waiting`}>{disputes.open + disputes.in_review}</span>}</Link>
      <Link href="/admin/approvals" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">✅ Approvals (roster changes, phone numbers)</Link>
      {isGlobalAdmin && <Link href="/admin/rules" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">📏 Rule versions</Link>}
      {isGlobalAdmin && <Link href="/admin/audit" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">🧾 Audit log</Link>}
      <Link href="/history" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">🏆 Season history</Link>
      <Link href="/admin/adjustments" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">⚖️ Points adjustments</Link>
      <Link href="/admin/duties" className="block card-elevated rounded-2xl border bg-card p-3 text-center text-sm">🧑‍⚖️ Umpire duties</Link>
      <h1 className="text-2xl font-bold text-primary">Seasons</h1>
      {seasons.length === 0 && <p className="text-sm text-muted-foreground">No seasons to manage yet.</p>}
      <ul className="space-y-2">
        {seasons.map((s) => (
          <li key={s.id}>
            <Link href={`/admin/seasons/${s.id}`} className="flex justify-between card-elevated rounded-2xl border bg-card p-3">
              <span>{s.name}</span>
              <span className="text-sm text-muted-foreground">{s.status}</span>
            </Link>
          </li>
        ))}
      </ul>
      {isGlobalAdmin && <form className="space-y-3" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        try { await post("/seasons", { name, status: "active" }); setName(""); await load(); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <Field label="New season name (e.g. FFCL S-24)" required value={name} onChange={(e) => setName(e.target.value)} />
        <ErrorText msg={err} />
        <button className={btnCls}>Create season</button>
      </form>}
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Admin /></RequireAuth>;
}
