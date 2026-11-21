# Changelog

## Unveröffentlicht

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
