"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/Logo";
import { btnCls, ErrorText, Field } from "@/components/ui-bits";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";

type Invite = { name: string; team: string | null; season: string | null; phone_ending: string };

export default function Join() {
  const { token } = useParams<{ token: string }>();
  const { acceptInvite } = useAuth();
  const router = useRouter();
  const [inv, setInv] = useState<Invite | null>(null);
  const [gone, setGone] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<Invite>(`/invites/${encodeURIComponent(token)}`).then(setInv).catch(() => setGone(true)); }, [token]);

  if (gone) return <p role="alert" className="text-sm">This invite link is no longer valid. Ask an organiser for a new one. <Link className="underline" href="/login">Sign in</Link></p>;
  if (!inv) return <p className="text-sm text-muted-foreground">Loading…</p>;
  return (
    <form className="space-y-4" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true); setErr(null);
      try { await acceptInvite(token, email, password); router.replace("/profile"); } catch (x) { setErr((x as Error).message); }
      setBusy(false);
    }}>
      <div className="flex justify-center"><Logo size={72} /></div>
      <h1 className="text-xl font-semibold">Welcome, {inv.name}</h1>
      <p className="text-sm">You have been added to <b>{inv.team}</b>{inv.season ? ` for ${inv.season}` : ""}. Your number ending {inv.phone_ending} is already verified. Choose an email and a password to finish.</p>
      <Field label="Email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password (min 8)" type="password" minLength={8} required autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <ErrorText msg={err} />
      <button className={btnCls} disabled={busy}>Join {inv.team}</button>
    </form>
  );
}
