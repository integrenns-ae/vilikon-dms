import { sprache } from "@/lib/utils";

/**
 * Every text of the page in both languages – the instance decides (<html lang>, set by the server from
 * VILIKON_LANGUAGE). New texts go into both blocks; `en` is checked against `de`, so none can be forgotten.
 * Kinds of letters and the reasons for "check" come translated from the server (app/texts).
 */
const de = {
  app: "Post",
  untertitel: "Werkzeug",
  schliessen: "Schließen",
  fehlerAllgemein: "Das hat nicht geklappt. Versuch es gleich noch einmal.",
  mail: {
    title: "Post",
    text: "Briefe vom Scanner und vom Handy: gelesen, nach Vorgang abgelegt, Fristen erkannt.",
    upload: "Brief hochladen",
    reading: "Wird gelesen …",
    readingText: "Der Brief wird gelesen. Das dauert meist weniger als eine Minute.",
    review: "Zu prüfen",
    inbox: "Eingang",
    pages: (n: string, cap: string | null) => (cap ? `${n} von ${cap} Seiten diesen Monat` : `${n} Seiten diesen Monat`),
    waiting: (n: number) => (n === 1 ? "1 Brief wartet" : `${n} Briefe warten`),
    reviewEmptyTitle: "Nichts zu prüfen",
    reviewEmptyText: "Alle Briefe sind eindeutig gelesen und abgelegt.",
    inboxEmptyTitle: "Noch keine Post",
    inboxEmptyText: "Fotografier einen Brief oder wähle ein PDF: Er wird gelesen und hier abgelegt.",
    columns: { date: "Datum", letter: "Brief", kind: "Art", status: "Status" },
    confidential: "vertraulich",
    open: "Brief öffnen",
    fileNumber: (n: string) => `Az. ${n}`,
  },
  status: { new: "Wird gelesen", waiting: "Wartet", done: "Abgelegt", review: "Prüfen", error: "Fehler" },
  stores: {
    title: "Ablagen",
    text: "Die Scanner-Ordner, aus denen Post abgeholt wird. Nur du siehst sie.",
    fetch: "Jetzt abholen",
    none: "Kein Scanner-Ordner verbunden: Post kommt nur über das Hochladen.",
    noneHelp: "Der IT-Betreuer richtet ihn im Tresor als Eintrag SCANNER der Art Dateiablage ein.",
    neverFetched: "Noch nicht abgeholt",
    lastFetch: (when: string) => `Zuletzt ${when}`,
    failed: "Fehler",
    newKey: "Neuer Schlüssel",
    accept: "Neuen Schlüssel annehmen",
    acceptText: "Der Server zeigt einen anderen Schlüssel als bisher. Nimm ihn nur an, wenn der Server neu eingerichtet wurde.",
  },
};

const en: typeof de = {
  app: "Mail",
  untertitel: "Tool",
  schliessen: "Close",
  fehlerAllgemein: "That didn't work. Please try again in a moment.",
  mail: {
    title: "Mail",
    text: "Letters from the scanner and the phone: read, filed by case, due dates found.",
    upload: "Upload a letter",
    reading: "Reading …",
    readingText: "The letter is being read. This usually takes less than a minute.",
    review: "To check",
    inbox: "Inbox",
    pages: (n: string, cap: string | null) => (cap ? `${n} of ${cap} pages this month` : `${n} pages this month`),
    waiting: (n: number) => (n === 1 ? "1 letter waiting" : `${n} letters waiting`),
    reviewEmptyTitle: "Nothing to check",
    reviewEmptyText: "Every letter was read clearly and filed.",
    inboxEmptyTitle: "No mail yet",
    inboxEmptyText: "Take a photo of a letter or choose a PDF: it is read and filed here.",
    columns: { date: "Date", letter: "Letter", kind: "Kind", status: "Status" },
    confidential: "confidential",
    open: "Open the letter",
    fileNumber: (n: string) => `Ref. ${n}`,
  },
  status: { new: "Reading", waiting: "Waiting", done: "Filed", review: "Check", error: "Error" },
  stores: {
    title: "File stores",
    text: "The scanner folders mail is fetched from. Only you see them.",
    fetch: "Fetch now",
    none: "No scanner folder connected: mail comes in only by uploading.",
    noneHelp: "The IT Specialist sets it up in the vault as the entry SCANNER of type file store.",
    neverFetched: "Not fetched yet",
    lastFetch: (when: string) => `Last ${when}`,
    failed: "Error",
    newKey: "New key",
    accept: "Accept the new key",
    acceptText: "The server shows a different key than before. Accept it only if the server was set up anew.",
  },
};

export const T = sprache === "en" ? en : de;
