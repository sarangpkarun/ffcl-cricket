"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { BottomNav } from "@/components/BottomNav";
import { TopBar } from "@/components/TopBar";
import { useAuth } from "@/lib/auth";

function PublicHeader() {
  const { me } = useAuth();
  return (
    <header className="sticky top-0 z-10 border-b bg-background/90 backdrop-blur">
      <div className="mx-auto flex h-12 max-w-3xl items-center justify-between gap-3 px-4">
        <Link href="/" className="font-semibold">FFCL</Link>
        <nav aria-label="Site" className="flex items-center gap-4 text-sm">
          <Link href="/league">Seasons</Link>
          <Link href="/league/history">History</Link>
          {me ? <Link href="/fixtures" className="rounded-md border px-3 py-1">Open the app</Link> : <Link href="/login" className="rounded-md border px-3 py-1">Sign in</Link>}
        </nav>
      </div>
    </header>
  );
}

/**
 * Two looks for one app: the narrow phone layout with bottom tabs for signed-in play, and a wider,
 * simpler layout for the public site. Public pages are chosen by address so the server renders the right
 * one; the home page shows the public look until we know the visitor is signed in.
 */
export function Chrome({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { me } = useAuth();
  const isPublic = path.startsWith("/league") || (path === "/" && !me);
  if (isPublic) {
    return (
      <>
        <PublicHeader />
        <main className="mx-auto w-full max-w-3xl flex-1 px-4 pb-12 pt-4">{children}</main>
        <footer className="border-t py-4 text-center text-xs text-muted-foreground">FFCL digit cricket league</footer>
      </>
    );
  }
  return (
    <>
      <TopBar />
      <main className="mx-auto w-full max-w-md flex-1 px-4 pb-24 pt-4">{children}</main>
      <Suspense fallback={null}>
        <BottomNav />
      </Suspense>
    </>
  );
}
