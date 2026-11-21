import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** The language of the instance (set on <html lang> when the template was applied): "de" or "en". */
export const sprache: "de" | "en" = document.documentElement.lang === "en" ? "en" : "de";
const locale = sprache === "en" ? "en-US" : "de-DE";

export function datum(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(locale, { day: "2-digit", month: "2-digit", year: "numeric" });
}

/** A day as the DMS stores it ("2026-11-18"): no time, no time zone. */
export function tag(iso: string | null | undefined): string {
  const d = iso ? new Date(`${iso.slice(0, 10)}T12:00:00`) : null;
  return d && !Number.isNaN(d.getTime()) ? d.toLocaleDateString(locale, { day: "2-digit", month: "2-digit", year: "numeric" }) : iso || "–";
}

/** A moment ("2026-11-21T08:40:00+00:00") in the browser's time: day and time. */
export function zeitpunkt(iso: string | null | undefined): string {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime())
    ? d.toLocaleString(locale, { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" })
    : iso || "–";
}

export function zahl(n: number, stellen = 0): string {
  return n.toLocaleString(locale, { minimumFractionDigits: stellen, maximumFractionDigits: stellen });
}
