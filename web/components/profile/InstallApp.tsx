"use client";

import { useEffect, useState } from "react";
import { btnCls } from "@/components/ui-bits";
import { HOW, isStandalone, platform, useInstallEvent, type Platform } from "@/lib/install";

/** A permanent place to install the app, for anyone who dismissed the banner or never got it. */
export function InstallApp() {
  const event = useInstallEvent();
  const [state, setState] = useState<{ installed: boolean; kind: Platform } | null>(null);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- the device is only known in the browser
  useEffect(() => { setState({ installed: isStandalone(), kind: platform() }); }, []);
  if (!state) return null;
  return (
    <section aria-label="Install the app" className="space-y-2 rounded-lg border p-4">
      <h2 className="font-medium">Install the app</h2>
      {state.installed ? <p className="text-sm">FFCL is installed on this device.</p>
        : event ? <button className={btnCls} onClick={async () => { await event.prompt(); await event.userChoice; }}>Install FFCL</button>
        : state.kind !== "other" ? <p className="text-sm">{HOW[state.kind]}</p>
        : <p className="text-sm">In Chrome or Edge, use the install icon at the right of the address bar. On a phone, open this page there and use the browser menu.</p>}
    </section>
  );
}
