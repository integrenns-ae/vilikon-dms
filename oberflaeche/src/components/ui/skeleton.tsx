import { cn } from "@/lib/utils";

/** A grey placeholder while data loads – shaped like what will come (rows, a card), never a spinner alone. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("rounded-[var(--radius)] bg-muted motion-safe:animate-pulse", className)} />;
}

export function ZeilenSkeleton({ zeilen = 4 }: { zeilen?: number }) {
  return (
    <div className="space-y-2" aria-busy>
      {Array.from({ length: zeilen }, (_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}
