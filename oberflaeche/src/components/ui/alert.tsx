import { cn } from "@/lib/utils";

export function Alert({ tone = "info", className, children }: { tone?: "info" | "error" | "success" | "warning"; className?: string; children: React.ReactNode }) {
  const t = {
    info: "border-border bg-muted text-foreground",
    error: "border-destructive/30 bg-destructive/10 text-destructive",
    success: "border-success/30 bg-success/10 text-success",
    warning: "border-warning/40 bg-warning/15 text-foreground",
  }[tone];
  return <div className={cn("rounded-[var(--radius)] border px-3 py-2 text-sm", t, className)}>{children}</div>;
}
