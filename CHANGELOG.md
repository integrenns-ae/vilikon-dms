# Changelog

## Unveröffentlicht

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
