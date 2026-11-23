import { api, loadTokens, saveTokens } from "@/lib/api";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

test("when another tab already refreshed, this tab uses the tokens it saved", async () => {
  saveTokens({ access_token: "old", refresh_token: "r1" });
  const seen: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init: RequestInit) => {
    const auth = (init.headers as Record<string, string>).Authorization;
    if (String(url).endsWith("/auth/refresh")) {
      saveTokens({ access_token: "fresh", refresh_token: "r2" }); // the other tab got there first
      return json(401, { detail: "Invalid refresh token" });
    }
    seen.push(auth);
    return auth === "Bearer fresh" ? json(200, { ok: true }) : json(401, { detail: "Session ended" });
  }));
  expect(await api("/me")).toEqual({ ok: true });
  expect(loadTokens()?.refresh_token).toBe("r2");
  expect(seen).toEqual(["Bearer old", "Bearer fresh"]);
});

test("a refresh that really fails ends the session, but a server error does not", async () => {
  saveTokens({ access_token: "old", refresh_token: "r1" });
  vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/auth/refresh") ? json(500, {}) : json(401, { detail: "x" }))));
  await expect(api("/me")).rejects.toThrow();
  expect(loadTokens()).not.toBeNull();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => (String(url).endsWith("/auth/refresh") ? json(401, {}) : json(401, { detail: "x" }))));
  await expect(api("/me")).rejects.toThrow();
  expect(loadTokens()).toBeNull();
});
