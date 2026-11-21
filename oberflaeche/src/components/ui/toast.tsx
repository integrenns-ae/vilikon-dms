import * as React from "react";
import { CheckCircle2, CircleAlert } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Short confirmations after an action („Gespeichert“) bottom right; errors stay longer. Wrap the app in
 * <ToastProvider>, then `const toast = useToast(); toast("Gespeichert")` or `toast(text, "fehler")`.
 */
type Art = "ok" | "fehler";
type Toast = { id: number; text: string; art: Art };
const Ctx = React.createContext<(text: string, art?: Art) => void>(() => {});

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [liste, setListe] = React.useState<Toast[]>([]);
  const zeigen = React.useCallback((text: string, art: Art = "ok") => {
    const id = Date.now() + Math.random();
    setListe((l) => [...l, { id, text, art }]);
    setTimeout(() => setListe((l) => l.filter((x) => x.id !== id)), art === "fehler" ? 7000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={zeigen}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-4 bottom-20 z-50 flex flex-col items-end gap-2 md:bottom-6">
        {liste.map((t) => (
          <div
            key={t.id}
            className={cn(
              "pointer-events-auto flex max-w-sm items-center gap-2 glas-schwebend rounded-full px-4 py-2 text-sm font-medium motion-safe:animate-aufsteigen",
              t.art === "fehler" ? "border-destructive/30 text-destructive" : "border-border",
            )}
          >
            {t.art === "fehler" ? <CircleAlert className="h-4 w-4 shrink-0" /> : <CheckCircle2 className="h-4 w-4 shrink-0 text-success" />}
            {t.text}
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export function useToast() {
  return React.useContext(Ctx);
}
