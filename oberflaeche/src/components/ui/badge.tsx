import { cn } from "@/lib/utils";

const styles: Record<string, string> = {
  pending: "bg-muted text-muted-foreground",
  running: "bg-accent text-primary motion-safe:animate-pulse",
  succeeded: "bg-success/15 text-success",
  failed: "bg-destructive/15 text-destructive",
  awaiting_approval: "bg-warning/20 text-warning-foreground",
  neutral: "bg-muted text-muted-foreground",
  ok: "bg-success/15 text-success",
  warning: "bg-warning/20 text-warning-foreground",
};

export function Badge({ tone = "neutral", className, children }: { tone?: string; className?: string; children: React.ReactNode }) {
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold", styles[tone] ?? styles.neutral, className)}>
      {children}
    </span>
  );
}
