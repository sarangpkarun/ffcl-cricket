import type { Metadata } from "next";
import { Suspense } from "react";
import { Dashboard } from "@/components/Dashboard";
import { HomeSwitch } from "@/components/HomeSwitch";
import { Landing } from "@/components/league/Landing";
import { Skeleton } from "@/components/league/PublicBits";

export const metadata: Metadata = { title: { absolute: "FFCL digit cricket league" }, alternates: { canonical: "/" } };

export default function Home() {
  return (
    <HomeSwitch landing={<Suspense fallback={<Skeleton />}><Landing /></Suspense>}>
      <Dashboard />
    </HomeSwitch>
  );
}
