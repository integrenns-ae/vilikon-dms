import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";

/** Load something from the own server: { daten, laedt, fehler, neuLaden }. Enough for small apps. */
export function useDaten<T>(pfad: string | null) {
  const [daten, setDaten] = useState<T | undefined>(undefined);
  const [laedt, setLaedt] = useState(!!pfad);
  const [fehler, setFehler] = useState<string | null>(null);
  const [runde, setRunde] = useState(0);

  useEffect(() => {
    if (!pfad) return;
    let aktiv = true;
    api<T>(pfad)
      .then((d) => aktiv && (setDaten(d), setFehler(null)))
      .catch((e: Error) => aktiv && setFehler(e.message))
      .finally(() => aktiv && setLaedt(false));
    return () => {
      aktiv = false;
    };
  }, [pfad, runde]);

  const neuLaden = useCallback(() => setRunde((r) => r + 1), []);
  return { daten, laedt, fehler, neuLaden, setDaten };
}
