import { useSyncExternalStore } from "react";

export type InstallEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> };

/**
 * Chrome and Edge fire `beforeinstallprompt` once, when the app becomes installable, and never again for that page. It is
 * caught here, as soon as this file loads, so it is not lost if it arrives before the page has finished starting up.
 */
let saved: InstallEvent | null = null;
const subscribers = new Set<() => void>();
const tell = () => subscribers.forEach((f) => f());
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); saved = e as InstallEvent; tell(); });
  window.addEventListener("appinstalled", () => { saved = null; tell(); });
}

export function useInstallEvent(): InstallEvent | null {
  return useSyncExternalStore((cb) => { subscribers.add(cb); return () => { subscribers.delete(cb); }; }, () => saved, () => null);
}

export const isStandalone = () => window.matchMedia("(display-mode: standalone)").matches || (navigator as Navigator & { standalone?: boolean }).standalone === true;

export type Platform = "ios" | "ios-app" | "android" | "other";
/** Which instructions fit this device. iPadOS 13+ calls itself a Mac, so a Mac with a touch screen is an iPad. Apps like WhatsApp open links in
 *  their own browser (no "Safari/" in its name) which has no Add to Home Screen. */
export function platform(): Platform {
  const ua = navigator.userAgent;
  if (/iphone|ipad|ipod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)) return /safari\//i.test(ua) ? "ios" : "ios-app";
  if (/android/i.test(ua)) return "android";
  return "other";
}

export const HOW: Record<Exclude<Platform, "other">, string> = {
  ios: "Tap the Share button, then “Add to Home Screen”. Match alerts work once it is on your Home Screen.",
  "ios-app": "Open this page in Safari first (menu, “Open in Safari”), then tap Share and “Add to Home Screen”.",
  android: "Open the browser menu (⋮) and tap “Install app” or “Add to Home screen”.",
};
