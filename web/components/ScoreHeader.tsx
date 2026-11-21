type Props = {
  match: string;
  team: string;
  role: "BATTING" | "BOWLING";
  runs: number;
  wickets: number;
  target?: number;
};

export function ScoreHeader({ match, team, role, runs, wickets, target }: Props) {
  return (
    <section className="rounded-lg border p-4">
      <p className="text-xs text-muted-foreground">{match}</p>
      <p className="mt-1 text-sm font-medium">
        {team} · {role}
      </p>
      <p className="text-3xl font-bold">
        {runs}/{wickets}
      </p>
      {target !== undefined && <p className="text-sm text-muted-foreground">Target: {target}</p>}
    </section>
  );
}
