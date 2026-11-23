import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Put the title, description and share-preview tags in <head> for every visitor, not just a list of known search bots.
  // Link previews (WhatsApp, Facebook, iMessage) and simple crawlers read only the head, and the data they need is the
  // same cached call the page makes anyway, so the cost is small.
  htmlLimitedBots: /.*/,
  cacheComponents: true,
  partialPrefetching: true,
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
