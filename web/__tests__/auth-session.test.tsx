import { act, render, screen, waitFor } from "@testing-library/react";
import { AuthProvider, useAuth } from "@/lib/auth";

const KEY = "ffcl.tokens";
const ME = { id: 1, player_code: "FFP1", name: "Asha", email: "a@t.io", phone: null, phone_verified: true, show_publicly: true, roles: ["player"], admin: { is_global: false, seasons: [] }, avatar_url: null, status: "active" };

function Probe() {
  const { me, loading, unreachable } = useAuth();
  return <p data-testid="state">{loading ? "loading" : me ? `signed in as ${me.name}` : unreachable ? "unreachable" : "signed out"}</p>;
}

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const stored = () => localStorage.getItem(KEY);

beforeEach(() => {
  localStorage.setItem(KEY, JSON.stringify({ access_token: "a", refresh_token: "r" }));
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  localStorage.clear();
});

test("a failed network request does not sign anyone out, and it is retried", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  let calls = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    if (String(url).endsWith("/me")) {
      calls += 1;
      if (calls === 1) throw new TypeError("Failed to fetch"); // the browser cancelled it, or the connection dropped
      return json(200, ME);
    }
    throw new Error(`unexpected ${url}`);
  }));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("unreachable"));
  expect(stored()).not.toBeNull(); // the sign-in is kept
  await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
  await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed in as Asha"));
  expect(calls).toBe(2);
});

test("a server error does not sign anyone out either", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(500, { detail: "oops" })));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("unreachable"));
  expect(stored()).not.toBeNull();
});

test("a real refusal (the session is over) does sign out and clears the saved sign-in", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(401, { detail: "Session ended" })));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed out"));
  expect(stored()).toBeNull();
});

test("a suspended account is signed out", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json(403, { detail: "Account not active" })));
  render(<AuthProvider><Probe /></AuthProvider>);
  await waitFor(() => expect(screen.getByTestId("state")).toHaveTextContent("signed out"));
  expect(stored()).toBeNull();
});
