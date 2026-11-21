import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** What a list shows when there is nothing in it: an icon, one sentence why, and the next step as a button. */
export function Leer({
  icon: Icon,
  titel,
  text,
  aktion,
  className,
}: {
  icon: LucideIcon;
  titel: string;
  text?: string;
  aktion?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center gap-2 rounded-[var(--radius)] border border-dashed border-border px-6 py-10 text-center", className)}>
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-accent text-primary">
        <Icon className="h-5 w-5" />
      </span>
      <p className="font-medium">{titel}</p>
      {text && <p className="max-w-sm text-sm text-muted-foreground">{text}</p>}
      {aktion && <div className="pt-1">{aktion}</div>}
    </div>
  );
}
