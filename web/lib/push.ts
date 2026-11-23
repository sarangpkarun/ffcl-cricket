import { api, post } from "@/lib/api";

export type PushState = "unsupported" | "disabled" | "denied" | "off" | "on";

const supported = () => typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function keyToBytes(base64Url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64Url.length % 4)) % 4);
  const raw = atob((base64Url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export async function registerServiceWorker(): Promise<ServiceWorkerRegistration | null> {
  if (!supported()) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" });
  } catch {
    return null;
  }
}

/** Where push stands on this device: not possible here, off on the server, blocked by the person, off, or on. */
export async function pushState(): Promise<PushState> {
  if (!supported()) return "unsupported";
  const key = await api<{ enabled: boolean }>("/push/key").catch(() => ({ enabled: false }));
  if (!key.enabled) return "disabled";
  if (Notification.permission === "denied") return "denied";
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  return sub && Notification.permission === "granted" ? "on" : "off";
}

/** Ask permission, subscribe this browser and tell the server about it. Throws a readable Error if it cannot. */
export async function enablePush(): Promise<void> {
  if (!supported()) throw new Error("This browser cannot receive push notifications. On an iPhone, add FFCL to the Home Screen first.");
  const { enabled, key } = await api<{ enabled: boolean; key: string | null }>("/push/key");
  if (!enabled || !key) throw new Error("Push notifications are not switched on for this server.");
  if ((await Notification.requestPermission()) !== "granted") throw new Error("Notifications are blocked. Allow them in your browser's site settings, then try again.");
  const reg = (await registerServiceWorker()) ? await navigator.serviceWorker.ready : null;
  if (!reg) throw new Error("Could not start the background service on this device.");
  const sub = (await reg.pushManager.getSubscription()) ?? (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyToBytes(key) }));
  await post("/me/push/subscriptions", sub.toJSON());
}

export async function disablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.getRegistration();
  const sub = await reg?.pushManager.getSubscription();
  if (!sub) return;
  await post("/me/push/subscriptions/remove", { endpoint: sub.endpoint }).catch(() => {});
  await sub.unsubscribe();
}
