/**
 * Talking to the own server – always with relative paths ("api/…"): the app lives under /werkzeug/<projekt>/.
 * In the Werkstatt preview (/vorschau/<projekt>/) there is no server; there every call answers with the example
 * data from lib/beispiel.ts, so the owner (and the screenshot) sees a filled app instead of an error.
 */
export const istVorschau = location.pathname.includes("/vorschau/");

export class ApiFehler extends Error {
  constructor(message: string, public status: number) {
    super(message);
  }
}

export async function api<T>(pfad: string, init: RequestInit = {}): Promise<T> {
  if (istVorschau) {
    const { beispielAntwort } = await import("./beispiel");
    return beispielAntwort(pfad, init) as T;
  }
  // JSON bodies get their type; a FormData body (the photos of a letter) sets its own multipart boundary.
  const json = init.body && !(init.body instanceof FormData);
  const r = await fetch(pfad, {
    ...init,
    headers: json ? { "Content-Type": "application/json", ...init.headers } : init.headers,
  });
  if (!r.ok) {
    let text = "";
    try {
      text = ((await r.json()) as { fehler?: string }).fehler ?? "";
    } catch {
      /* no JSON */
    }
    throw new ApiFehler(text || `Fehler ${r.status}`, r.status);
  }
  return r.status === 204 ? (undefined as T) : ((await r.json()) as T);
}
