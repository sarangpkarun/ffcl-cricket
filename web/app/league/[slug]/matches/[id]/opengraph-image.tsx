import { ImageResponse } from "next/og";
import { pubPlain, type PubMatch } from "@/lib/public";

export const alt = "FFCL match";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export default async function Image({ params }: { params: Promise<{ slug: string; id: string }> }) {
  const { id } = await params;
  const m = await pubPlain<PubMatch>(`/matches/${id}`);
  const match = m?.live.match;
  const a = match ? match.teams[String(match.team_a_id)] : "FFCL";
  const b = match ? match.teams[String(match.team_b_id)] : "";
  const inn = m?.live.innings ?? [];
  const score = (n: number) => { const i = inn.find((x) => x.number === n); return i ? `${i.runs}/${i.wickets} (${i.overs})` : ""; };
  return new ImageResponse(
    (
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", width: "100%", height: "100%", background: "#111", color: "#fff", padding: 80 }}>
        <div style={{ fontSize: 34, color: "#bbb" }}>{`${m?.season.name ?? "FFCL"}${m?.round_label ? ` · ${m.round_label}` : ""}`}</div>
        <div style={{ fontSize: 84, fontWeight: 800, marginTop: 24 }}>{b ? `${a} vs ${b}` : a}</div>
        {inn.length > 0 && <div style={{ fontSize: 44, marginTop: 24 }}>{inn.length > 1 ? `${score(1)}  ·  ${score(2)}` : score(1)}</div>}
        {match?.result && <div style={{ fontSize: 40, marginTop: 24, color: "#9f9" }}>{match.result}</div>}
      </div>
    ),
    size,
  );
}
