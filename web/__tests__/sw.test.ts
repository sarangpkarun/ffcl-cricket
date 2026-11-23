import { readFileSync } from "node:fs";
import { join } from "node:path";

type Handler = (e: Record<string, unknown>) => void;

/** Load public/sw.js against a fake service-worker environment so its push and click logic can be tested. */
function load() {
  const handlers: Record<string, Handler> = {};
  const shown: { title: string; options: Record<string, unknown> }[] = [];
  const opened: string[] = [];
  const focused: { url: string; navigated?: string }[] = [];
  let clients: { url: string; focus: () => Promise<unknown> }[] = [];
  const self = {
    addEventListener: (type: string, h: Handler) => { handlers[type] = h; },
    registration: { showNotification: async (title: string, options: Record<string, unknown>) => { shown.push({ title, options }); } },
    location: { origin: "https://ffcl.test" },
    skipWaiting: async () => {},
    clients: {
      claim: async () => {},
      openWindow: async (url: string) => { opened.push(url); },
      matchAll: async () => clients,
    },
  };
  const cache = { addAll: async () => {} };
  const caches = { open: async () => cache, keys: async () => [], delete: async () => true, match: async () => undefined };
  new Function("self", "caches", "fetch", "Response", "URL", readFileSync(join(process.cwd(), "public", "sw.js"), "utf8"))(self, caches, async () => { throw new Error("offline"); }, { error: () => "error-response" }, URL);
  const waits: Promise<unknown>[] = [];
  const fire = async (type: string, e: Record<string, unknown>) => {
    handlers[type]({ ...e, waitUntil: (p: Promise<unknown>) => waits.push(p) });
    await Promise.all(waits.splice(0));
  };
  return {
    fire, shown, opened, focused,
    setClients: (urls: string[]) => { clients = urls.map((url) => ({ url, focus: async () => ({ navigate: async (to: string) => { focused.push({ url, navigated: to }); } }) })); },
  };
}

const pushEvent = (data: unknown) => ({ data: { json: () => { if (data === "bad") throw new Error("not json"); return data; } } });

test("a push shows its title, body and in-app link", async () => {
  const sw = load();
  await sw.fire("push", pushEvent({ id: 7, title: "Match 1 has a result", body: "Pink won", link: "/matches/1" }));
  expect(sw.shown).toHaveLength(1);
  expect(sw.shown[0].title).toBe("Match 1 has a result");
  expect(sw.shown[0].options).toMatchObject({ body: "Pink won", tag: "ffcl-7", data: { link: "/matches/1" } });
});

test("odd pushes still show something sensible and never carry a link off the site", async () => {
  const sw = load();
  await sw.fire("push", pushEvent("bad"));
  await sw.fire("push", pushEvent({}));
  await sw.fire("push", pushEvent({ title: "x".repeat(500), body: "y".repeat(500), link: "https://evil.test/phish" }));
  await sw.fire("push", pushEvent({ title: "a", link: "//evil.test" }));
  await sw.fire("push", { data: null });
  expect(sw.shown.map((s) => s.title)).toEqual(["FFCL", "FFCL", "x".repeat(100), "a", "FFCL"]);
  expect((sw.shown[2].options.body as string).length).toBe(200);
  for (const s of sw.shown) expect((s.options.data as { link: string }).link).toBe("/notifications");
});

test("tapping a notification opens its page, reusing an open window", async () => {
  const sw = load();
  const close = () => {};
  await sw.fire("notificationclick", { notification: { close, data: { link: "/matches/9" } } });
  expect(sw.opened).toEqual(["https://ffcl.test/matches/9"]);
  sw.setClients(["https://ffcl.test/fixtures"]);
  await sw.fire("notificationclick", { notification: { close, data: { link: "/standings" } } });
  expect(sw.focused).toEqual([{ url: "https://ffcl.test/fixtures", navigated: "https://ffcl.test/standings" }]);
  await sw.fire("notificationclick", { notification: { close, data: { link: "https://evil.test" } } });
  expect(sw.focused[1].navigated).toBe("https://ffcl.test/notifications");
  await sw.fire("notificationclick", { notification: { close, data: undefined } });
  expect(sw.focused[2].navigated).toBe("https://ffcl.test/notifications");
});
