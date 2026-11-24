# Changelog

## Unveröffentlicht

## 0.4.1

- Zwei Werte stellst du jetzt im Cockpit ein, auf der Seite „Werkzeuge“ unter „Verwalten“: wie oft die Post in den
  Ablagen nach neuen Briefen schaut (bisher fest 10 Minuten) und ab wie vielen Tagen ein alter Brief beim ersten
  Abruf einer Ablage nur abgelegt statt gemeldet wird (bisher fest 30).
- Jeder Brief zeigt auf der Seite „Post“ eine kleine Vorschau: die erste Seite des Scans oder das Foto. Ein Klick
  darauf öffnet den ganzen Brief groß in einem Fenster, das sich mit dem Kreuz, mit Escape oder mit einem Klick
  daneben schließt; herunterladen lässt er sich dort auch. Ein Klick auf den Titel öffnet ihn wie bisher in einem
  neuen Tab.

## 0.4.0

- Mitarbeiter mit dem Recht „Post einsehen“ holen das Original eines Briefs (den Scan oder das Foto) in ihre
  Arbeitsmappe und können es so an eine Mail hängen; für vertrauliche Briefe braucht es „Vertrauliche Post einsehen“.
  Die Datei heißt nach Datum und Absender.

## 0.3.0

- Die Seite „Post“ sieht jetzt aus wie das Cockpit: dieselben Farben, dieselbe Schrift, dieselben Karten und
  Knöpfe, auch auf dem Handy und im Dunkelmodus. Ändert der Inhaber die Farbe des Cockpits, zieht sie mit.
- „Zu prüfen“ und „Eingang“ als Reiter mit Anzahl; Art, Status und „vertraulich“ stehen als kleine Marken an jedem
  Brief.
- Ein Klick auf einen Brief öffnet ihn, so lässt sich ein unklares Datum gleich im Brief nachsehen. Vertrauliche
  Briefe öffnet nur der Inhaber.
- Fotos oder ein PDF wählen lädt den Brief gleich hoch, ohne zweiten Knopf.

## 0.2.2

- Wird ein Scanner-Ordner zum ersten Mal abgeholt, werden ältere Briefe, die schon dort lagen (mehr als 30 Tage vor dem
  Abholen datiert), nur abgelegt: Sie sind auffindbar und ihre Fristen bleiben gespeichert, aber sie werden keine
  Aufgaben und Vorgänge für den Inhaber mehr.
- Ein Datum, das schon vorbei ist, wird keine neue Frist im Kalender mehr.
- Erkennt Post bei einem Beleg den Betrag, den Absender oder das Datum nicht, steht der Brief jetzt auf „prüfen“ und
  sagt, was fehlt. Bisher ging so ein Beleg still verloren, statt in der Buchhaltung anzukommen.

## 0.2.1

- Liest Post einen Brief vom Handy nicht, sagt die Antwort jetzt, warum: etwa dass er mehr Seiten hat, als im
  Monat gelesen werden dürfen, oder dass die Seiten des Monats aufgebraucht sind.

## 0.2.0

- Post ist jetzt ein Werkzeug: Der IT-Betreuer installiert es aus dem Katalog, ohne eigenen Container.
- Zugangsdaten kommen aus dem Tresor: der Scanner-Ordner als Eintrag `SCANNER` der Art Dateiablage (weitere als
  `SCANNER2` …), der Schlüssel für die Texterkennung als Eintrag `OCR`. Post speichert selbst keine Passwörter mehr und
  löscht beim ersten Start, was frühere Versionen gespeichert hatten.
- Der Schlüssel des Betreibers hat eine feste Zahl von Seiten pro Monat. Ein eigener Mistral-Schlüssel hat keine
  Grenze.
- Neues Recht „Post einrichten“: Wer es hat, sieht, ob jede Ablage antwortet und die Texterkennung einen Schlüssel hat,
  und kann sofort abholen lassen.
- Abgeholt wird im Hintergrund, das erste Mal wenige Sekunden nach dem Start. Die Karte „Post: Seiten“ zeigt, welche Ablage
  gerade nicht antwortet.
- Auf der Seite „Post“ sieht der Inhaber die Ablagen und kann sofort abholen.
- SFTP-Ablagen werden an ihrem Schlüssel erkannt. Zeigt der Server plötzlich einen anderen, holt Post nichts mehr ab,
  bis der Inhaber den neuen Schlüssel auf der Seite annimmt.
- Vertrauliche Briefe sieht nur der Inhaber; das prüft Post jetzt richtig.
- Fotos vom Handy brauchen viel weniger Speicher: Die Seiten werden einzeln zusammengesetzt. Höchstens 60 MB pro Brief
  und 40 Megapixel pro Foto.

## 0.1.0

- Post aus der Ablage: Der Scanner legt Briefe in einen SFTP- oder FTP-Ordner, das Modul holt sie ab, liest sie mit
  Mistral und legt sie ab. Derselbe Brief zweimal wird nur einmal gelesen.
- Post vom Handy: mehrere Fotos eines Briefs werden ein PDF.
- Erkannt werden Art, Absender, Datum, Aktenzeichen, was zu tun ist, Fristen, Betrag, IBAN und Verwendungszweck, ob es
  ein Beleg ist und ob er vertraulich ist. Post vom Gericht oder Anwalt ist immer vertraulich und geht nur an den
  Inhaber; eine unklare Frist wird nie geraten, der Brief kommt auf „prüfen“.
- Briefe mit demselben Aktenzeichen bilden einen Vorgang.
- Eigene Seite im Menü „Post“: Eingang, Liste „prüfen“ und Hochladen vom Handy. Vertrauliche Briefe sieht nur der
  Inhaber.
- Seitengrenze pro Monat (Vorgabe 500 Seiten); darüber warten Briefe bis zum Monatsanfang. Ein eigener Mistral-Schlüssel hebt sie auf.
- Anschluss ans Cockpit: Firmengedächtnis (vertrauliche Briefe vertraulich), Ereignisse für Aufgaben, zwei Karten,
  Funktionen zum Suchen, für Fristen und Belegdaten.
