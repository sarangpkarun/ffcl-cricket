"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { btnCls, ErrorText, Field, RequireAuth } from "@/components/ui-bits";
import { api, post, type Season } from "@/lib/api";

function Admin() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<Season[]>("/seasons").then(setSeasons).catch((e) => setErr(e.message)), []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-5">
      <Link href="/admin/users" className="block rounded-lg border p-3 text-center text-sm">👥 People (roles, suspend)</Link>
      <Link href="/admin/moderation" className="block rounded-lg border p-3 text-center text-sm">🛡️ Chat moderation (reports, mutes, announcements)</Link>
      <h1 className="text-xl font-semibold">Seasons</h1>
      <ul className="space-y-2">
        {seasons.map((s) => (
          <li key={s.id}>
            <Link href={`/seasons/${s.id}`} className="flex justify-between rounded-lg border p-3">
              <span>{s.name}</span>
              <span className="text-sm text-muted-foreground">{s.status}</span>
            </Link>
          </li>
        ))}
      </ul>
      <form className="space-y-3" onSubmit={async (e) => {
        e.preventDefault();
        setErr(null);
        try { await post("/seasons", { name, status: "active" }); setName(""); await load(); }
        catch (x) { setErr((x as Error).message); }
      }}>
        <Field label="New season name (e.g. FFCL S-24)" required value={name} onChange={(e) => setName(e.target.value)} />
        <ErrorText msg={err} />
        <button className={btnCls}>Create season</button>
      </form>
    </div>
  );
}

export default function Page() {
  return <RequireAuth admin><Admin /></RequireAuth>;
}
