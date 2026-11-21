import { ScoreHeader } from "@/components/ScoreHeader";

export default function Home() {
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">FFCL Season 24</h1>
      <ScoreHeader match="MATCH 1 · OVER 1" team="Team Pink" role="BATTING" runs={0} wickets={0} target={33} />
      <p className="text-sm text-muted-foreground">Live matches will appear here.</p>
    </div>
  );
}
