"use client";

import { useEffect, useState } from "react";
import { inputCls } from "@/components/ui-bits";
import { api, type UserLite } from "@/lib/api";

export function UserSearch({ onPick, label }: { onPick: (u: UserLite) => void; label: string }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<UserLite[]>([]);
  useEffect(() => {
    if (q.length < 2) return;
    const t = setTimeout(() => {
      api<UserLite[]>(`/users?q=${encodeURIComponent(q)}`).then(setRows).catch(() => setRows([]));
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="space-y-2">
      <input className={inputCls} placeholder={label} value={q} onChange={(e) => setQ(e.target.value)} />
      <ul className="space-y-1">
        {(q.length < 2 ? [] : rows).map((u) => (
          <li key={u.id}>
            <button type="button" className="w-full rounded-md border px-3 py-2 text-left text-sm" onClick={() => { onPick(u); setQ(""); }}>
              {u.name} <span className="text-muted-foreground">{u.player_code}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
