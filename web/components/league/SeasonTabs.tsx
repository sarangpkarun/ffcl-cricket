"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

const TABS = [
  { seg: "", label: "Overview" }, { seg: "fixtures", label: "Fixtures" }, { seg: "results", label: "Results" },
  { seg: "table", label: "Table" }, { seg: "stats", label: "Stats" }, { seg: "insights", label: "Insights" }, { seg: "rules", label: "Rules" },
];

export function SeasonTabs({ slug, seasons }: { slug: string; seasons: { slug: string; name: string }[] }) {
  const path = usePathname();
  const router = useRouter();
  const rest = path.slice(`/league/${slug}`.length).split("/").filter(Boolean)[0] ?? "";
  const tab = TABS.some((t) => t.seg === rest) ? rest : null;
  return (
    <div className="space-y-2">
      {seasons.length > 1 && (
        <select aria-label="Season" className="w-full rounded-md border bg-background px-3 py-2 text-sm sm:w-auto" value={slug}
          onChange={(e) => router.push(`/league/${e.target.value}${tab ? `/${tab}` : ""}`)}>
          {seasons.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
        </select>
      )}
      <nav aria-label="Season pages" className="-mx-4 flex overflow-x-auto border-b px-4">
        {TABS.map((t) => {
          const active = tab === t.seg;
          return (
            <Link key={t.seg} href={`/league/${slug}${t.seg ? `/${t.seg}` : ""}`} aria-current={active ? "page" : undefined}
              className={`whitespace-nowrap px-3 py-2 text-sm ${active ? "border-b-2 border-foreground font-semibold" : "text-muted-foreground"}`}>
              {t.label}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
