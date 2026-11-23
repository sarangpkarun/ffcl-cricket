"use client";

import { useState } from "react";
import { btnGhost, ErrorText, inputCls } from "@/components/ui-bits";
import { post } from "@/lib/api";

export function VerifyPhone({ u, onDone }: { u: { id: number; name: string; phone: string | null }; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  return (
    <form className="space-y-2 rounded-md bg-muted p-2" onSubmit={async (e) => {
      e.preventDefault();
      setErr(null);
      try { await post(`/admin/users/${u.id}/verify-phone`, { reason }); setReason(""); onDone(); } catch (x) { setErr((x as Error).message); }
    }}>
      <label className="block text-xs">Why is {u.phone} genuine? (for example: called them, they are known to the team)
        <input className={inputCls} required minLength={3} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <button className={btnGhost}>Verify {u.name}&apos;s number</button>
      <ErrorText msg={err} />
    </form>
  );
}
