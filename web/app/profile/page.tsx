"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { btnCls, btnGhost, ErrorText, Field, RequireAuth } from "@/components/ui-bits";
import { api, del, post } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type PhoneChange = { id: number; new_phone: string; status: string; reason: string; decision_note: string | null } | null;

function PhoneChange({ onChanged }: { onChanged: () => void }) {
  const [req, setReq] = useState<PhoneChange>(null);
  const [form, setForm] = useState({ phone: "", reason: "" });
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => api<PhoneChange>("/me/phone-change").then(setReq).catch(() => {}), []);
  useEffect(() => { void load(); }, [load]);
  const run = async (fn: () => Promise<unknown>) => { setErr(null); try { await fn(); await load(); } catch (x) { setErr((x as Error).message); } };
  const open = req && (req.status === "pending" || req.status === "approved");

  return (
    <section aria-label="Change phone number" className="space-y-3 rounded-lg border p-4">
      <h2 className="font-medium">Change phone number</h2>
      <ErrorText msg={err} />
      {req?.status === "rejected" && <p className="text-sm text-red-700">Your last request was rejected: {req.decision_note}</p>}
      {req?.status === "completed" && <p className="text-sm text-green-700">Your number was changed.</p>}
      {open && req.status === "pending" && <p className="text-sm">Waiting for an admin to approve the change to {req.new_phone}.</p>}
      {open && req.status === "approved" && (
        <div className="space-y-2">
          <p className="text-sm">Approved. Confirm the new number {req.new_phone} with a code.</p>
          {!sent
            ? <button className={btnCls} onClick={() => run(async () => { await post("/me/phone-change/otp/request"); setSent(true); })}>Send code to the new number</button>
            : <>
                <Field label="6-digit code" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value)} />
                <button className={btnCls} disabled={code.length !== 6} onClick={() => run(async () => { await post("/me/phone-change/verify", { code }); setCode(""); setSent(false); onChanged(); })}>Confirm new number</button>
              </>}
        </div>
      )}
      {open && <button className={btnGhost} onClick={() => run(() => del("/me/phone-change"))}>Cancel this change</button>}
      {!open && (
        <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); await run(async () => { await post("/me/phone-change", { new_phone: form.phone, reason: form.reason }); setForm({ phone: "", reason: "" }); }); }}>
          <Field label="New mobile number" inputMode="tel" required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <Field label="Why are you changing it?" required minLength={3} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
          <button className={btnGhost}>Ask for approval</button>
        </form>
      )}
    </section>
  );
}

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
      {me.phone_verified && <PhoneChange onChanged={() => void reload()} />}

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
