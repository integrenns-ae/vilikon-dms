import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { Hilfe } from "@/components/ui/hilfe";
import { cn } from "@/lib/utils";

/**
 * A card may carry a tone: a tinted header and a round icon chip, so the owner recognises at a glance what
 * kind of card he is looking at (Tresor, settings, backup, health). The body always stays white.
 * Every colour is a design token, so the customer palette (lib/farben.ts) recolours the chips as well.
 */
export type CardTone = "tresor" | "einstellungen" | "sicherung" | "hinweis" | "gruen" | "gelb" | "rot";

const TONE: Record<CardTone, { kopf: string; chip: string }> = {
  // Dark label on amber: white on the warning colour is not readable.
  tresor: { kopf: "bg-warning/10", chip: "bg-warning text-[#0b1f4d]" },
  einstellungen: { kopf: "bg-accent/60", chip: "knopf-signal text-knopf-text" },
  sicherung: { kopf: "bg-success/10", chip: "bg-success text-white" },
  hinweis: { kopf: "bg-muted/60", chip: "bg-muted text-muted-foreground" },
  gruen: { kopf: "bg-success/10", chip: "bg-success text-white" },
  gelb: { kopf: "bg-warning/10", chip: "bg-warning text-[#0b1f4d]" },
  rot: { kopf: "bg-destructive/10", chip: "bg-destructive text-white" },
};

const ToneContext = React.createContext<CardTone | undefined>(undefined);

/**
 * True inside a collapsible section (ui/klappe) or a side panel (ui/panel) that already shows the title: a card
 * there drops its frame and its title row and keeps only its „?“, its action and its content.
 */
export const EinbettungContext = React.createContext(false);
const HilfeContext = React.createContext<React.ReactNode>(null);

export function Card({ tone, className, children, id, ...p }: React.HTMLAttributes<HTMLDivElement> & { tone?: CardTone }) {
  const eingebettet = React.useContext(EinbettungContext);
  if (eingebettet) {
    return (
      <ToneContext.Provider value={undefined}>
        <div className={className} {...p}>{children}</div>
      </ToneContext.Provider>
    );
  }
  return (
    <ToneContext.Provider value={tone}>
      <div id={id} className={cn("scroll-mt-4 rounded-[var(--radius)] border border-border bg-card", className)} {...p}>
        {children}
      </div>
    </ToneContext.Provider>
  );
}

/** Explanations of a card: not shown as text, but behind the „?“ next to its title. */
export function CardHilfe({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

export function CardHeader({ className, children, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  const tone = React.useContext(ToneContext);
  const eingebettet = React.useContext(EinbettungContext);
  const teile = React.Children.toArray(children);
  const istHilfe = (c: React.ReactNode) => React.isValidElement(c) && c.type === CardHilfe;
  const hilfe = teile.filter(istHilfe);
  return (
    <HilfeContext.Provider value={hilfe.length ? <div className="space-y-2">{hilfe}</div> : null}>
      <div
        className={cn(
          "group flex flex-col gap-1",
          eingebettet ? "pb-2" : "p-4 pb-2 sm:p-5 sm:pb-2",
          !eingebettet && tone && cn("rounded-t-[var(--radius)] border-b border-border pb-4", TONE[tone].kopf),
          className,
        )}
        {...p}
      >
        {teile.filter((c) => !istHilfe(c))}
      </div>
    </HilfeContext.Provider>
  );
}

/** `icon` becomes a round chip in the card's tone; `aktion` sits at the right end of the title row. */
export function CardTitle({
  icon: Icon,
  aktion,
  className,
  children,
  ...p
}: React.HTMLAttributes<HTMLHeadingElement> & { icon?: LucideIcon; aktion?: React.ReactNode }) {
  const tone = React.useContext(ToneContext);
  const eingebettet = React.useContext(EinbettungContext);
  const hilfe = React.useContext(HilfeContext);
  if (eingebettet) {
    // The section around it shows title and icon; here only what one can do.
    if (!hilfe && !aktion) return null;
    return (
      <div className="flex items-center justify-end gap-2 text-sm">
        {hilfe && <Hilfe>{hilfe}</Hilfe>}
        {aktion}
      </div>
    );
  }
  return (
    <h3 className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-base font-bold leading-tight tracking-tight", className)} {...p}>
      {Icon && (
        <span
          className={cn(
            "flex h-7 w-7 shrink-0 items-center justify-center rounded-full",
            tone ? TONE[tone].chip : "bg-accent text-primary",
          )}
        >
          <Icon className="h-4 w-4 motion-safe:group-hover:animate-wiggle" />
        </span>
      )}
      <span className="min-w-0">{children}</span>
      {hilfe && <Hilfe className="font-normal">{hilfe}</Hilfe>}
      {aktion && <span className="ml-auto shrink-0 text-sm font-normal">{aktion}</span>}
    </h3>
  );
}

export function CardDescription({ className, ...p }: React.HTMLAttributes<HTMLParagraphElement>) {
  return <p className={cn("text-sm text-muted-foreground", className)} {...p} />;
}

export function CardContent({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) {
  const tone = React.useContext(ToneContext);
  const eingebettet = React.useContext(EinbettungContext);
  return <div className={cn(eingebettet ? "pt-1" : "p-4 pt-2 sm:p-5 sm:pt-2", !eingebettet && tone && "pt-4 sm:pt-4", className)} {...p} />;
}
