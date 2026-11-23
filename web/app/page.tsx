import type { Metadata } from "next";
import { Suspense } from "react";
import { HomeSwitch } from "@/components/HomeSwitch";
import { Landing } from "@/components/league/Landing";
import { Skeleton } from "@/components/league/PublicBits";
import { ScoreHeader } from "@/components/ScoreHeader";

export const metadata: Metadata = { title: { absolute: "FFCL digit cricket league" }, alternates: { canonical: "/" } };

function Dashboard() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">FFCL Season 24</h1>
      <ScoreHeader match="MATCH 1 · OVER 1" team="Team Pink" role="BATTING" runs={0} wickets={0} target={33} />
      <p className="text-sm text-muted-foreground">Live matches will appear here.</p>
    </div>
  );
}

export default function Home() {
  return (
    <HomeSwitch landing={<Suspense fallback={<Skeleton />}><Landing /></Suspense>}>
      <Dashboard />
    </HomeSwitch>
  );
}
