import type { NextConfig } from "next";

/**
 * Security headers for every page.
 *
 * The policy blocks every script, frame, plugin and form target that is not ours. `script-src` keeps 'unsafe-inline'
 * because Next puts small inline scripts in each page and a per-request nonce would make every page dynamic (no more
 * static pages or partial prerendering, which keep the public site fast). The app never renders raw HTML (a test
 * enforces it), so an injected tag has nowhere to come from. Development also needs eval and a socket for hot reload.
 */
const api = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
const dev = process.env.NODE_ENV !== "production";
const policy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${dev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${api.origin} ${api.protocol === "https:" ? "wss" : "ws"}://${api.host}${dev ? " ws://localhost:* http://localhost:*" : ""}`,
  "manifest-src 'self'",
  "worker-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");
const securityHeaders = [
  { key: "Content-Security-Policy", value: policy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  /* config options here */
  // Put the title, description and share-preview tags in <head> for every visitor, not just a list of known search bots.
  // Link previews (WhatsApp, Facebook, iMessage) and simple crawlers read only the head, and the data they need is the
  // same cached call the page makes anyway, so the cost is small.
  htmlLimitedBots: /.*/,
  cacheComponents: true,
  partialPrefetching: true,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
