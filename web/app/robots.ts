import type { MetadataRoute } from "next";
import { SITE } from "@/lib/public";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: ["/", "/league"], disallow: ["/admin", "/chat", "/profile", "/notifications", "/login", "/register", "/matches/", "/teams/", "/players/", "/fixtures", "/standings", "/leaderboards", "/history", "/seasons", "/join/"] }],
    sitemap: `${SITE}/sitemap.xml`,
  };
}
