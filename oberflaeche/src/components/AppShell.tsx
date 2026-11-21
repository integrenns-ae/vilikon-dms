import type { LucideIcon } from "lucide-react";
import { AppWindow } from "lucide-react";
import { cn } from "@/lib/utils";
import { gehe } from "@/lib/route";
import { T } from "@/texte";

export interface NavPunkt {
  pfad: string;
  label: string;
  icon: LucideIcon;
}

/** Inside the cockpit (iframe) the cockpit already shows its sidebar – the app then shows a slim tab row only. */
const eingebettet = typeof window !== "undefined" && window.self !== window.top;

/**
 * The frame of every app, like the cockpit itself: sidebar with brand line and navigation on wide screens, a top
 * bar plus a bottom tab bar on the phone, a slim tab row when embedded. `aktiv` is the current route's first part.
 */
export function AppShell({ nav, aktiv, children }: { nav: NavPunkt[]; aktiv: string; children: React.ReactNode }) {
  const ist = (p: NavPunkt) => aktiv === p.pfad;

  if (eingebettet) {
    return (
      <div className="min-h-full">
        {nav.length > 1 && (
          <nav className="glas sticky top-0 z-10 flex gap-1 overflow-x-auto border-b px-4 py-2">
            {nav.map((p) => (
              <NavKnopf key={p.pfad} p={p} aktiv={ist(p)} />
            ))}
          </nav>
        )}
        <main className="mx-auto max-w-5xl p-4 md:p-6">{children}</main>
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col md:flex-row">
      <aside className="glas flex shrink-0 items-center gap-2 border-b px-4 py-3 md:sticky md:top-0 md:h-screen md:w-56 md:flex-col md:items-stretch md:border-b-0 md:border-r md:py-5">
        <div className="flex items-center gap-2 md:mb-5 md:px-3">
          <AppWindow className="h-5 w-5 text-primary motion-safe:animate-float" />
          <div className="leading-tight">
            <div className="text-base font-extrabold tracking-tight">{T.app}</div>
            <div className="hidden text-xs text-muted-foreground md:block">{T.untertitel}</div>
          </div>
        </div>
        <nav className="hidden flex-col gap-0.5 md:flex">
          {nav.map((p) => (
            <NavKnopf key={p.pfad} p={p} aktiv={ist(p)} />
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-4 pb-24 md:p-6">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
      {nav.length > 1 && (
        <nav className="glas fixed inset-x-0 bottom-0 z-20 flex justify-around border-t px-2 py-1.5 md:hidden">
          {nav.map((p) => (
            <button
              key={p.pfad}
              type="button"
              onClick={() => gehe(p.pfad)}
              aria-current={ist(p) ? "page" : undefined}
              className={cn("flex min-w-16 flex-col items-center gap-0.5 rounded-[var(--radius)] px-3 py-1 text-[10px]", ist(p) ? "text-primary" : "text-muted-foreground")}
            >
              <p.icon className="h-5 w-5" />
              {p.label}
            </button>
          ))}
        </nav>
      )}
    </div>
  );
}

function NavKnopf({ p, aktiv }: { p: NavPunkt; aktiv: boolean }) {
  return (
    <button
      type="button"
      onClick={() => gehe(p.pfad)}
      aria-current={aktiv ? "page" : undefined}
      className={cn(
        "group flex items-center gap-2 whitespace-nowrap rounded-[var(--radius)] px-3 py-2 text-left text-sm transition-colors hover:bg-muted",
        aktiv && "bg-accent font-medium text-primary hover:bg-accent",
      )}
    >
      <p.icon className="h-4 w-4 transition-transform group-hover:scale-110" />
      {p.label}
    </button>
  );
}

/** The head of every page: title, one sentence what it is for, actions on the right. */
export function Seitenkopf({ titel, text, aktion }: { titel: string; text?: string; aktion?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-extrabold tracking-tight">{titel}</h1>
        {text && <p className="max-w-3xl text-sm text-muted-foreground">{text}</p>}
      </div>
      {aktion && <div className="flex shrink-0 flex-wrap gap-2">{aktion}</div>}
    </div>
  );
}
