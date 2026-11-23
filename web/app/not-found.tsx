import Link from "next/link";

export default function NotFound() {
  return (
    <div className="space-y-3 py-10 text-center">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <p className="text-sm text-muted-foreground">That page does not exist, or it is not public.</p>
      <p><Link className="underline" href="/league">See the seasons</Link></p>
    </div>
  );
}
