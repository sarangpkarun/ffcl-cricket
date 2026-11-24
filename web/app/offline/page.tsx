import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = { title: "Offline", robots: { index: false } };

export default function Offline() {
  return (
    <div className="space-y-3 py-10 text-center">
      <h1 className="text-2xl font-bold text-primary">You are offline</h1>
      <p className="text-sm text-muted-foreground">FFCL needs a connection to show live scores and to play. Check your signal and try again. Nothing you did has been lost.</p>
      <p><Link className="underline" href="/">Try again</Link></p>
    </div>
  );
}
