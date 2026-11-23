"use client";

import { useEffect, useState } from "react";
import { SeasonInsightsView } from "@/components/league/Analytics";
import { ErrorText, inputCls, RequireAuth } from "@/components/ui-bits";
import { api, type Season } from "@/lib/api";
import type { SeasonAnalytics } from "@/lib/analytics";

function Insights() {
  const [seasons, setSeasons] = useState<Season[]>([]);
  const [sid, setSid] = useState("");
  const [d, setD] = useState<SeasonAnalytics | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api<Season[]>("/seasons").then((s) => { setSeasons(s); setSid(String((s.find((x) => x.status === "active") ?? s[0])?.id ?? "")); }).catch((e) => setErr(e.message)); }, []);
  useEffect(() => { if (sid) api<SeasonAnalytics>(`/seasons/${sid}/analytics`).then((x) => { setD(x); setErr(null); }).catch((e) => setErr(e.message)); }, [sid]);
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Season insights</h1>
      <select aria-label="Season" className={inputCls} value={sid} onChange={(e) => setSid(e.target.value)}>{seasons.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
      <ErrorText msg={err} />
      {d && <SeasonInsightsView data={d} teamHref={(id) => `/teams/${id}`} />}
    </div>
  );
}

export default function Page() {
  return <RequireAuth><Insights /></RequireAuth>;
}
