import type { MetadataRoute } from "next";
import { LOGO } from "@/lib/logo";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "FFCL digit cricket league",
    short_name: "FFCL",
    description: "Play, umpire and follow FFCL digit cricket: live scores, fixtures, table and stats.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: LOGO.brand,
    theme_color: LOGO.brand,
    categories: ["sports"],
    icons: [
      { src: "/icons/192", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/512", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icons/maskable", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
    shortcuts: [
      { name: "Fixtures", url: "/fixtures" },
      { name: "Points table", url: "/standings" },
      { name: "Notifications", url: "/notifications" },
    ],
  };
}
