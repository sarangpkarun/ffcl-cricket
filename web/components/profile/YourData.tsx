"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { btnGhost, ErrorText, inputCls } from "@/components/ui-bits";
import { api, download, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

/** Download everything held about you, or leave the league. */
export function YourData() {
  const { logout } = useAuth();
  const router = useRouter();
  const [check, setCheck] = useState<{ can_delete: boolean; blockers: string[] } | null>(null);
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<{ can_delete: boolean; blockers: string[] }>("/me/delete-check").then(setCheck).catch(() => {}); }, []);
  return (
    <section aria-label="Your data" className="space-y-3 card-elevated rounded-2xl border bg-card p-4">
      <h2 className="font-medium">Your data</h2>
      <p className="text-sm">See <Link className="underline" href="/privacy">how your data is used</Link>.</p>
      <button className={btnGhost} onClick={async () => { setErr(null); try { await download("/me/data", "ffcl-my-data.json"); } catch (e) { setErr((e as Error).message); } }}>Download my data</button>
      <details className="rounded-md border p-3">
        <summary className="cursor-pointer text-sm font-medium text-destructive">Delete my account</summary>
        <div className="mt-2 space-y-2 text-sm">
          <p>Your name, email, phone number and password are removed and you are signed out everywhere. Your matches stay in the results as <b>Former player</b>, so tables and statistics do not change. This cannot be undone.</p>
          {check && check.blockers.length > 0 && <ul role="status" className="list-disc space-y-1 pl-5">{check.blockers.map((b) => <li key={b}>{b}</li>)}</ul>}
          <form className="space-y-2" onSubmit={async (e) => {
            e.preventDefault();
            setErr(null);
            try { await post("/me/delete", { password }); await logout(); router.replace("/"); } catch (x) { setErr((x as Error).message); }
          }}>
            <label className="block">Your password to confirm
              <input className={inputCls} type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
            <button className={`${btnGhost} border-destructive text-destructive`} disabled={!check?.can_delete || !password}>Delete my account for good</button>
          </form>
        </div>
      </details>
      <ErrorText msg={err} />
    </section>
  );
}
