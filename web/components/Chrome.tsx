"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense } from "react";
import { Logo } from "@/components/Logo";
import { BottomNav } from "@/components/BottomNav";
import { TopBar } from "@/components/TopBar";
import { useAuth } from "@/lib/auth";

function PublicHeader() {
  const { me } = useAuth();
  return (
    <header className="hero-gradient sticky top-0 z-10 shadow-md">
      <div className="mx-auto flex h-14 max-w-3xl items-center justify-between gap-3 px-4">
        <Link href="/" prefetch={false} className="flex items-center gap-2 font-bold tracking-wide"><Logo size={30} />FFCL</Link>
        <nav aria-label="Site" className="flex items-center gap-4 text-sm">
          <Link href="/league" prefetch={false}>Seasons</Link>
          <Link href="/league/history" prefetch={false}>History</Link>
          {me ? <Link href="/fixtures" className="rounded-full bg-white px-3 py-1 font-medium text-primary">Open the app</Link> : <Link href="/login" prefetch={false} className="rounded-full bg-white px-3 py-1 font-medium text-primary">Sign in</Link>}
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
  const isPublic = path.startsWith("/league") || ["/privacy", "/terms"].includes(path) || (path === "/" && !me);
  if (isPublic) {
    return (
      <>
        <PublicHeader />
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl flex-1 px-4 pb-12 pt-4 outline-none">{children}</main>
        <footer className="border-t py-4 text-center text-xs text-muted-foreground">FFCL digit cricket league · <Link className="underline" href="/privacy" prefetch={false}>Privacy</Link> · <Link className="underline" href="/terms" prefetch={false}>Terms</Link></footer>
      </>
    );
  }
  return (
    <>
      <TopBar />
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-md flex-1 px-4 pb-24 pt-4 outline-none">{children}</main>
      <Suspense fallback={null}>
        <BottomNav />
      </Suspense>
    </>
  );
}
