import { cn } from "@/lib/utils";

/** Switches between views of the same thing (Offen / Erledigt / Alle). `anzahl` shows a small count. */
export function Tabs<T extends string>({
  wert,
  setWert,
  optionen,
  className,
}: {
  wert: T;
  setWert: (w: T) => void;
  optionen: { wert: T; label: string; anzahl?: number }[];
  className?: string;
}) {
  return (
    <div role="tablist" className={cn("inline-flex max-w-full gap-1 overflow-x-auto [scrollbar-width:none] rounded-full border border-border bg-card p-1", className)}>
      {optionen.map((o) => (
        <button
          key={o.wert}
          role="tab"
          type="button"
          aria-selected={o.wert === wert}
          onClick={() => setWert(o.wert)}
          className={cn(
            "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40",
            o.wert === wert ? "knopf-signal font-semibold text-knopf-text" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {o.label}
          {o.anzahl !== undefined && (
            <span className={cn("rounded-full px-1.5 text-[10px] font-semibold", o.wert === wert ? "bg-white/25 text-knopf-text" : "bg-muted text-muted-foreground")}>
              {o.anzahl}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
