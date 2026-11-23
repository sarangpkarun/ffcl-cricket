"use client";

import { useEffect, useState } from "react";

type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };
const KEY = "ffcl.install.dismissed";

const standalone = () => window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent) && !/crios|fxios/i.test(navigator.userAgent);

function remembered(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

/** Offers to install FFCL: Chrome and Edge give us a prompt, Safari on iPhone needs the Share menu so we explain it. */
export function InstallPrompt() {
  const [event, setEvent] = useState<InstallEvent | null>(null);
  const [ios, setIos] = useState(false);
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    if (standalone() || remembered()) return;
    const onPrompt = (e: Event) => {
      e.preventDefault(); // keep it until the person asks
      setEvent(e as InstallEvent);
      setHidden(false);
    };
    const onInstalled = () => setHidden(true);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    if (isIos()) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- iPhone has no install event, so show the hint
      setIos(true);
      setHidden(false);
    }
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const dismiss = () => {
    setHidden(true);
    try {
      localStorage.setItem(KEY, "1");
    } catch {
      /* private mode: it will ask again next visit */
    }
  };

  if (hidden || (!event && !ios)) return null;
  return (
    <aside aria-label="Install the app" className="fixed inset-x-3 bottom-16 z-20 mx-auto flex max-w-md items-center gap-3 rounded-lg border bg-background p-3 text-sm shadow-lg">
      <p className="flex-1">
        {event ? "Install FFCL on your phone for quick access and match alerts." : "To install FFCL, tap Share, then “Add to Home Screen”."}
      </p>
      {event && (
        <button className="rounded-md bg-foreground px-3 py-2 text-background" onClick={async () => { await event.prompt(); await event.userChoice; setEvent(null); dismiss(); }}>
          Install
        </button>
      )}
      <button className="rounded-md border px-3 py-2" onClick={dismiss} aria-label="Not now">Not now</button>
    </aside>
  );
}
