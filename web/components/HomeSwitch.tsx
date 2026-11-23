"use client";

import { useAuth } from "@/lib/auth";

/** Signed-in people get their dashboard; everyone else gets the public landing page that the server already rendered. */
export function HomeSwitch({ landing, children }: { landing: React.ReactNode; children: React.ReactNode }) {
  const { me } = useAuth();
  return <>{me ? children : landing}</>;
}
