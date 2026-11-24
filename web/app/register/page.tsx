"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { btnCls, ErrorText, Field } from "@/components/ui-bits";
import { Logo } from "@/components/Logo";
import { useAuth } from "@/lib/auth";

export default function Register() {
  const { register } = useAuth();
  const router = useRouter();
  const [f, setF] = useState({ name: "", email: "", password: "", phone: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await register({ ...f, phone: f.phone || undefined });
      router.replace("/profile");
    } catch (x) {
      setErr((x as Error).message);
    }
    setBusy(false);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="flex justify-center"><Logo size={72} /></div>
      <h1 className="text-2xl font-bold text-primary">Create account</h1>
      <Field label="Name" required value={f.name} onChange={set("name")} />
      <Field label="Email" type="email" required value={f.email} onChange={set("email")} />
      <Field label="Password (min 8)" type="password" minLength={8} required value={f.password} onChange={set("password")} />
      <Field label="Mobile number (used to play, e.g. +919876543210)" inputMode="tel" required value={f.phone} onChange={set("phone")} />
      <ErrorText msg={err} />
      <button className={btnCls} disabled={busy}>Register</button>
      <p className="text-sm">
        Have an account? <Link href="/login" className="underline">Sign in</Link>
      </p>
    </form>
  );
}
