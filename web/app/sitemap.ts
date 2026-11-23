import type { MetadataRoute } from "next";
import { SITE, pubPlain } from "@/lib/public";

type Sitemap = { seasons: string[]; teams: { id: number; season: string }[]; matches: { id: number; season: string }[]; players: { id: number; season: string }[] };

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const d = await pubPlain<Sitemap>("/sitemap");
  const u = (path: string, priority: number) => ({ url: `${SITE}${path}`, priority });
  const out = [u("/", 1), u("/league", 0.8), u("/league/history", 0.5)];
  if (!d) return out;
  for (const s of d.seasons) for (const p of ["", "/fixtures", "/results", "/table", "/stats", "/insights", "/rules"]) out.push(u(`/league/${s}${p}`, p === "" ? 0.9 : 0.7));
  for (const t of d.teams) out.push(u(`/league/${t.season}/teams/${t.id}`, 0.6));
  for (const m of d.matches) out.push(u(`/league/${m.season}/matches/${m.id}`, 0.6));
  for (const p of d.players) out.push(u(`/league/${p.season}/players/${p.id}`, 0.5));
  return out;
}
