import type { Letter, Mail } from "@/lib/typen";

/** Example data for a preview without the server (/vorschau/…): invented letters, two file stores. */
const letters: Letter[] = [
  {
    id: "a1", kind: "notice", kind_text: "Bescheid", sender: "Finanzamt Musterstadt", subject: "Bescheid über Umsatzsteuer 2025",
    title: "Finanzamt Musterstadt – Bescheid über Umsatzsteuer 2025", date: "2026-11-18", file_number: "123/456/78901",
    status: "review", reason: "Eine Frist ist nicht eindeutig. Bitte das Datum im Brief nachsehen.", confidential: false,
  },
  {
    id: "a2", kind: "court", kind_text: "Gericht", sender: "Amtsgericht Musterstadt", subject: "Ladung zum Termin",
    title: "Amtsgericht Musterstadt – Ladung zum Termin", date: "2026-11-17", file_number: "4 C 123/26",
    status: "review", reason: "Post vom Gericht oder Anwalt ohne erkennbare Frist. Bitte nachsehen.", confidential: true,
  },
  {
    id: "a3", kind: "invoice", kind_text: "Rechnung", sender: "Musterfirma GmbH", subject: "Rechnung 2026-117",
    title: "Musterfirma GmbH – Rechnung 2026-117", date: "2026-11-15", file_number: "2026-117", status: "done", reason: "",
    confidential: false,
  },
  {
    id: "a4", kind: null, kind_text: "", sender: null, subject: null, title: "scan.pdf", date: "2026-11-14", file_number: null,
    status: "waiting", reason: "Die Seiten für diesen Monat sind aufgebraucht. Das Dokument wartet bis zum Monatsanfang.",
    confidential: false,
  },
  {
    id: "a5", kind: "advertising", kind_text: "Werbung", sender: "Beispiel Versand AG", subject: "Herbstkatalog",
    title: "Beispiel Versand AG – Herbstkatalog", date: "2026-11-12", file_number: null, status: "done", reason: "",
    confidential: false,
  },
];

const mail: Mail = {
  review: letters.filter((l) => l.status === "review"),
  documents: letters,
  pages: { month: "2026-11", pages: 212, cap: 500, own_key: false, waiting: 1 },
  owner: true,
  sources: [
    { id: "scanner", protocol: "sftp", host: "nas.example.com", error: "", last_fetch: "2026-11-21T08:40:00+00:00", host_key_new: "" },
    {
      id: "scanner2", protocol: "sftp", host: "buero.example.com", error: "Der Server zeigt einen anderen Schlüssel als bisher.",
      last_fetch: "2026-11-19T16:10:00+00:00", host_key_new: "ssh-ed25519 SHA256:bmV1ZXItc2NobHVlc3NlbA",
    },
  ],
};

export function beispielAntwort(pfad: string, init: RequestInit): unknown {
  const methode = (init.method ?? "GET").toUpperCase();
  if (pfad === "api/documents") return mail;
  if (pfad === "api/upload" && methode === "POST")
    return { id: "a9", duplicate: false, status: "done", text: "Gelesen und abgelegt." };
  if (pfad.endsWith("/checked") && methode === "POST") return { text: "Der Brief ist als geprüft abgelegt." };
  if (methode === "POST") return { text: "Die Ablagen werden jetzt abgeholt." };
  return null;
}
