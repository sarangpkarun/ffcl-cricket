"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { btnCls, ErrorText, Field } from "@/components/ui-bits";
import { useAuth } from "@/lib/auth";

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (x) {
      setErr((x as Error).message);
    }
    setBusy(false);
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <h1 className="text-xl font-semibold">Sign in</h1>
      <Field label="Email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
      <Field label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
      <ErrorText msg={err} />
      <button className={btnCls} disabled={busy}>Sign in</button>
      <p className="text-sm">
        New player? <Link href="/register" className="underline">Create an account</Link>
      </p>
    </form>
  );
}
