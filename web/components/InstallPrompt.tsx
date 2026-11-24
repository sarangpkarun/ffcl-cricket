"use client";

import { useEffect, useState } from "react";
import { HOW, isStandalone, platform, useInstallEvent, type Platform } from "@/lib/install";

const KEY = "ffcl.install.dismissed";
const ANDROID_WAIT_MS = 6000; // how long to wait for Chrome's own install offer before explaining the menu instead

function remembered(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/**
 * Offers to install FFCL. Chrome and Edge give us an install button; iPhone and iPad have none, so we explain the Share menu; and if an
 * Android browser does not offer the button (Chrome decides that itself), we explain the menu after a few seconds.
 */
export function InstallPrompt() {
  const event = useInstallEvent();
  const [kind, setKind] = useState<Platform | null>(null);
  const [eligible, setEligible] = useState(false); // not installed yet and not dismissed
  const [late, setLate] = useState(false);

  useEffect(() => {
    if (isStandalone() || remembered()) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the device is only known in the browser
    setKind(platform());
    setEligible(true);
    const t = setTimeout(() => setLate(true), ANDROID_WAIT_MS);
    return () => clearTimeout(t);
  }, []);

  const dismiss = () => {
    setEligible(false);
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      /* private mode: it will ask again next visit */
    }
  };

  const how = kind && kind !== "other" && (kind !== "android" || late) ? HOW[kind] : null;
  if (!eligible || (!event && !how)) return null;
  return (
    <aside aria-label="Install the app" className="fixed inset-x-3 bottom-20 z-20 mx-auto flex max-w-md items-center gap-3 rounded-lg border bg-background p-3 text-sm shadow-lg">
      <p className="flex-1">{event ? "Install FFCL on your phone for quick access and match alerts." : `To install FFCL: ${how}`}</p>
      {event && (
        <button className="rounded-md bg-foreground px-3 py-2 text-background" onClick={async () => { await event.prompt(); await event.userChoice; dismiss(); }}>
          Install
        </button>
      )}
      <button className="rounded-md border px-3 py-2" onClick={dismiss} aria-label="Not now">Not now</button>
    </aside>
  );
}
