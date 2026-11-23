/* FFCL service worker.
 *
 * What it does, and only this:
 *  1. Shows push notifications and opens the right page when one is tapped.
 *  2. If a page cannot load because the phone is offline, shows a friendly offline page.
 *
 * It never stores API responses or pages: live scores and the table must always come fresh from the server,
 * so nothing stale can ever be shown as current.
 */
const VERSION = "ffcl-sw-v1";
const OFFLINE_URL = "/offline";
const ICON = "/icons/192";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(VERSION).then((c) => c.addAll([OFFLINE_URL, ICON])).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.mode !== "navigate") return; // only whole pages; everything else goes straight to the network
  event.respondWith(fetch(req).catch(async () => (await caches.match(OFFLINE_URL)) || Response.error()));
});

/** Only paths inside this site are ever opened from a notification. */
function safePath(link) {
  if (typeof link !== "string" || !link.startsWith("/") || link.startsWith("//") || link.includes("\\")) return "/notifications";
  return link;
}

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    data = {};
  }
  const title = typeof data.title === "string" && data.title ? data.title.slice(0, 100) : "FFCL";
  const options = {
    body: typeof data.body === "string" ? data.body.slice(0, 200) : "",
    icon: ICON,
    badge: ICON,
    tag: data.id ? "ffcl-" + data.id : undefined,
    data: { link: safePath(data.link) },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(safePath(event.notification.data && event.notification.data.link), self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
      for (const c of clients) {
        if (new URL(c.url).origin === self.location.origin && "focus" in c) {
          return c.focus().then((f) => ("navigate" in f ? f.navigate(url) : undefined));
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
