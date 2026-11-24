/** A pulsing placeholder block shown while content loads. */
export function Skeleton({ className = "h-20" }: { className?: string }) {
  return <div aria-hidden className={`animate-pulse rounded-2xl bg-muted ${className}`} />;
}

export function ListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading" className="space-y-3">
      <Skeleton className="h-24" />
      {Array.from({ length: rows }, (_, i) => <Skeleton key={i} className="h-28" />)}
    </div>
  );
}
