import * as React from "react";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { T } from "@/texte";

/**
 * A modal on the native <dialog>: focus trap, Esc and the backdrop come from the browser. `offen` controls it,
 * `schliessen` is called on Esc, backdrop click and the X. Actions go into `fuss` (right-aligned).
 */
export function Dialog({
  offen,
  schliessen,
  titel,
  beschreibung,
  fuss,
  className,
  children,
}: {
  offen: boolean;
  schliessen: () => void;
  titel: React.ReactNode;
  beschreibung?: React.ReactNode;
  fuss?: React.ReactNode;
  className?: string;
  children?: React.ReactNode;
}) {
  const ref = React.useRef<HTMLDialogElement>(null);
  React.useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (offen && !d.open) d.showModal();
    if (!offen && d.open) d.close();
  }, [offen]);

  return (
    <dialog
      ref={ref}
      onClose={schliessen}
      onClick={(e) => e.target === ref.current && schliessen()}
      className={cn(
        "m-auto w-[calc(100%-2rem)] max-w-lg glas-schwebend rounded-3xl p-0 text-card-foreground backdrop:bg-[#071536]/30 backdrop:backdrop-blur-[2px]",
        className,
      )}
    >
      <div className="flex items-start gap-3 p-5 pb-2">
        <div className="min-w-0 flex-1 space-y-1">
          <h2 className="text-base font-bold leading-tight tracking-tight">{titel}</h2>
          {beschreibung && <p className="text-sm text-muted-foreground">{beschreibung}</p>}
        </div>
        <button type="button" onClick={schliessen} aria-label={T.schliessen} className="rounded-[var(--radius)] p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </div>
      {children && <div className="p-5 pt-2">{children}</div>}
      {fuss && <div className="flex flex-wrap justify-end gap-2 border-t border-border px-5 py-3">{fuss}</div>}
    </dialog>
  );
}
