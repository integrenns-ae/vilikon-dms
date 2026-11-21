import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";

const BREITE = 288; // px, max width of the bubble

/**
 * A small bubble at a trigger: opens on hover, focus and tap (phones have no hover), closes on Esc, on a click
 * elsewhere and when the page scrolls. Rendered into <body> with fixed coordinates, so a scrolling strip or a
 * collapsed card never clips it.
 */
export function Tipp({
  inhalt,
  label,
  children,
  className,
  breit = false,
}: {
  inhalt: React.ReactNode;
  label: string;
  children: React.ReactNode;
  className?: string;
  breit?: boolean;
}) {
  const [offen, setOffen] = React.useState(false);
  const [lage, setLage] = React.useState<React.CSSProperties>({});
  const ausloeser = React.useRef<HTMLButtonElement>(null);
  const blase = React.useRef<HTMLDivElement>(null);
  const hoverZu = React.useRef<number | null>(null);
  const id = React.useId();

  const platzieren = React.useCallback(() => {
    const r = ausloeser.current?.getBoundingClientRect();
    if (!r) return;
    const breite = Math.min(breit ? 384 : BREITE, window.innerWidth - 16);
    // centred on the trigger, as wide as the text needs (at most `breite`), never over the window's edge
    const mitte = Math.min(Math.max(r.left + r.width / 2, breite / 2 + 8), window.innerWidth - breite / 2 - 8);
    const lage = { left: mitte, transform: "translateX(-50%)", width: "max-content", maxWidth: breite } as const;
    const unten = window.innerHeight - r.bottom > 220 || r.top < 220;
    setLage(unten ? { ...lage, top: r.bottom + 6 } : { ...lage, bottom: window.innerHeight - r.top + 6 });
  }, [breit]);

  const auf = React.useCallback(() => {
    if (hoverZu.current) window.clearTimeout(hoverZu.current);
    platzieren();
    setOffen(true);
  }, [platzieren]);
  const zuSpaeter = () => {
    hoverZu.current = window.setTimeout(() => setOffen(false), 120);
  };

  React.useEffect(() => {
    if (!offen) return;
    const taste = (e: KeyboardEvent) => e.key === "Escape" && setOffen(false);
    const klick = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!ausloeser.current?.contains(t) && !blase.current?.contains(t)) setOffen(false);
    };
    const weg = () => setOffen(false);
    document.addEventListener("keydown", taste);
    document.addEventListener("pointerdown", klick);
    window.addEventListener("scroll", weg, true);
    window.addEventListener("resize", weg);
    return () => {
      document.removeEventListener("keydown", taste);
      document.removeEventListener("pointerdown", klick);
      window.removeEventListener("scroll", weg, true);
      window.removeEventListener("resize", weg);
    };
  }, [offen]);

  return (
    <>
      <button
        ref={ausloeser}
        type="button"
        aria-label={label}
        aria-expanded={offen}
        aria-describedby={offen ? id : undefined}
        className={cn("inline-flex shrink-0 items-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary", className)}
        onMouseEnter={auf}
        onMouseLeave={zuSpaeter}
        onFocus={auf}
        onClick={(e) => {
          e.stopPropagation();
          if (offen) setOffen(false);
          else auf();
        }}
      >
        {children}
      </button>
      {offen &&
        createPortal(
          <div
            ref={blase}
            id={id}
            role="tooltip"
            style={lage}
            onMouseEnter={() => hoverZu.current && window.clearTimeout(hoverZu.current)}
            onMouseLeave={zuSpaeter}
            className="glas-schwebend fixed z-[60] space-y-2 rounded-[var(--radius)] p-3 text-left text-xs font-normal leading-relaxed text-foreground motion-safe:animate-aufsteigen"
          >
            {inhalt}
          </div>,
          document.body,
        )}
    </>
  );
}
