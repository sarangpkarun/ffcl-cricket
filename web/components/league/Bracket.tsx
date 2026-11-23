import Link from "next/link";
import type { BracketMatch } from "@/lib/api";
import { LocalTime } from "@/components/league/LocalTime";

/** One knockout match. Shared by the signed-in app and the public site. */
export function Tie({ m, href }: { m: BracketMatch; href: string }) {
  const side = (t: BracketMatch["team_a"]) => (
    <span className={m.winner_team_id === t.id ? "font-semibold" : m.status === "completed" ? "text-muted-foreground" : ""}>
      {m.winner_team_id === t.id && "✓ "}{t.name}
    </span>
  );
  return (
    <Link href={href} className="block rounded-lg border p-3" aria-label={`${m.round_label}: ${m.team_a.name} vs ${m.team_b.name}`}>
      <p className="text-xs text-muted-foreground">{m.round_label} · #{m.match_no} · {m.status === "completed" ? "Final result" : <LocalTime iso={m.scheduled_at} />}</p>
      <p className="font-medium">{side(m.team_a)} <span className="text-muted-foreground">vs</span> {side(m.team_b)}</p>
      {m.result && <p className="text-sm">🏆 {m.result}</p>}
    </Link>
  );
}
