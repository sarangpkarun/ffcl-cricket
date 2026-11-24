import { act, fireEvent, render, screen } from "@testing-library/react";
import { InstallPrompt } from "@/components/InstallPrompt";

const UA = {
  iphoneSafari: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
  iphoneChrome: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/124.0.6367.88 Mobile/15E148 Safari/604.1",
  iphoneWhatsApp: "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  ipadAsMac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
  android: "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
  laptop: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
};

function device(ua: string, opts: { platform?: string; touch?: number; standalone?: boolean } = {}) {
  vi.spyOn(window.navigator, "userAgent", "get").mockReturnValue(ua);
  vi.spyOn(window.navigator, "platform", "get").mockReturnValue(opts.platform ?? "Linux x86_64");
  vi.spyOn(window.navigator, "maxTouchPoints", "get").mockReturnValue(opts.touch ?? 0);
  window.matchMedia = vi.fn().mockReturnValue({ matches: opts.standalone ?? false, addEventListener() {}, removeEventListener() {} }) as unknown as typeof window.matchMedia;
}
const banner = () => screen.queryByRole("complementary", { name: "Install the app" });

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); localStorage.clear(); });

test("iPhone Safari is told to use Share, then Add to Home Screen, and that alerts need it", () => {
  device(UA.iphoneSafari, { platform: "iPhone", touch: 5 });
  render(<InstallPrompt />);
  expect(banner()).toHaveTextContent(/Tap the Share button, then “Add to Home Screen”/);
  expect(banner()).toHaveTextContent(/alerts work once it is on your Home Screen/i);
  expect(screen.queryByRole("button", { name: "Install" })).toBeNull(); // iPhone has no install button to offer
});

test("Chrome on iPhone gets the same help (it also has Add to Home Screen)", () => {
  device(UA.iphoneChrome, { platform: "iPhone", touch: 5 });
  render(<InstallPrompt />);
  expect(banner()).toHaveTextContent(/Share button/);
});

test("an iPad that calls itself a Mac is recognised by its touch screen", () => {
  device(UA.ipadAsMac, { platform: "MacIntel", touch: 5 });
  render(<InstallPrompt />);
  expect(banner()).toHaveTextContent(/Share button/);
});

test("inside WhatsApp or Instagram the person is told to open Safari first", () => {
  device(UA.iphoneWhatsApp, { platform: "iPhone", touch: 5 });
  render(<InstallPrompt />);
  expect(banner()).toHaveTextContent(/Open this page in Safari first/i);
});

test("a laptop shows nothing until the browser offers to install", () => {
  device(UA.laptop);
  render(<InstallPrompt />);
  expect(banner()).toBeNull();
});

test("Android without Chrome's own offer is told about the menu after a few seconds", () => {
  vi.useFakeTimers();
  device(UA.android, { platform: "Linux armv81", touch: 5 });
  render(<InstallPrompt />);
  expect(banner()).toBeNull(); // give Chrome a moment to offer its own button
  act(() => { vi.advanceTimersByTime(6100); });
  expect(banner()).toHaveTextContent(/browser menu \(⋮\) and tap “Install app” or “Add to Home screen”/);
});

test("nothing is shown once it is installed, and Not now is remembered", () => {
  device(UA.iphoneSafari, { platform: "iPhone", touch: 5, standalone: true });
  const first = render(<InstallPrompt />);
  expect(banner()).toBeNull(); // already on the Home Screen
  first.unmount();
  device(UA.iphoneSafari, { platform: "iPhone", touch: 5 });
  const second = render(<InstallPrompt />);
  fireEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(banner()).toBeNull();
  second.unmount();
  render(<InstallPrompt />);
  expect(banner()).toBeNull(); // still hidden next visit
});

// last: the browser's install event is kept for the rest of the page's life
test("when Chrome offers to install, the Install button appears, even if the offer came before the banner was drawn", () => {
  device(UA.android, { platform: "Linux armv81", touch: 5 });
  const offer = Object.assign(new Event("beforeinstallprompt", { cancelable: true }), { prompt: vi.fn(async () => {}), userChoice: Promise.resolve({ outcome: "accepted" as const }) });
  act(() => { window.dispatchEvent(offer); }); // before anything is rendered
  render(<InstallPrompt />);
  expect(banner()).toHaveTextContent("Install FFCL on your phone for quick access and match alerts.");
  expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
});
