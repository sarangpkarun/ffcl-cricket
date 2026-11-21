"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, RequireAuth } from "@/components/ui-bits";
import { post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

function Profile() {
  const { me, reload, logout, isAdmin } = useAuth();
  const router = useRouter();
  const [sent, setSent] = useState(false);
  const [code, setCode] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!me) return null;

  async function run(fn: () => Promise<void>) {
    setErr(null);
    try {
      await fn();
    } catch (x) {
      setErr((x as Error).message);
    }
  }

  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold">My profile</h1>
      <section className="rounded-lg border p-4 text-sm space-y-1">
        <p className="text-base font-medium">{me.name}</p>
        <p>Player ID: <b>{me.player_code}</b></p>
        <p>{me.email}</p>
        <p>Mobile: {me.phone ?? "—"} {me.phone_verified ? "✅ verified" : "⚠️ not verified"}</p>
        <p>Roles: {me.roles.join(", ")}</p>
      </section>

      {me.phone && !me.phone_verified && (
        <section className="space-y-3 rounded-lg border p-4">
          <p className="text-sm">You must verify your registered number to play.</p>
          {!sent ? (
            <button className={btnCls} onClick={() => run(async () => { await post("/auth/otp/request", { phone: me.phone }); setSent(true); })}>
              Send OTP
            </button>
          ) : (
            <>
              <Field label="6-digit code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
              <button className={btnCls} disabled={code.length !== 6} onClick={() => run(async () => { await post("/auth/otp/verify", { phone: me.phone, code }); await reload(); })}>
                Verify
              </button>
            </>
          )}
        </section>
      )}
      <ErrorText msg={err} />

      {isAdmin && <Link href="/admin" className={`${btnGhost} block text-center`}>Admin dashboard</Link>}
      <div className="flex gap-3">
        <button className={`${btnGhost} flex-1`} onClick={async () => { await logout(); router.replace("/login"); }}>Log out</button>
        <button className={`${btnGhost} flex-1`} onClick={async () => { await logout(true); router.replace("/login"); }}>Log out everywhere</button>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <RequireAuth>
      <Profile />
    </RequireAuth>
  );
}
