"use client";

import { useEffect } from "react";
import { registerServiceWorker } from "@/lib/push";

/** Registers /sw.js once, so installs, the offline page and push work. Renders nothing. */
export function ServiceWorker() {
  useEffect(() => {
    void registerServiceWorker();
  }, []);
  return null;
}
