"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";

export const inputCls = "w-full rounded-md border bg-background px-3 py-3 text-base";
export const btnCls = "w-full rounded-md bg-foreground py-3 text-background disabled:opacity-40";
export const btnGhost = "rounded-md border px-3 py-2 text-sm";

export function Field({ label, ...p }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1 text-sm">
      <span>{label}</span>
      <input className={inputCls} {...p} />
    </label>
  );
}

export function ErrorText({ msg }: { msg: string | null }) {
  return msg ? (
    <p role="alert" className="text-sm text-red-600">
      {msg}
    </p>
  ) : null;
}

export function RequireAuth({ children, admin }: { children: React.ReactNode; admin?: boolean }) {
  const { me, loading, isAdmin } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);
  if (loading || !me) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (admin && !isAdmin)
    return (
      <p className="text-sm">
        Admins only. <Link href="/" className="underline">Back home</Link>
      </p>
    );
  return <>{children}</>;
}
