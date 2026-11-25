Wofür: die Briefpost des Betriebs. Briefe, Bescheide, Rechnungen und Post vom Gericht kommen vom Scanner oder als Foto vom Handy, werden gelesen, nach Vorgang abgelegt und ihre Fristen erkannt.

- Mit `search_documents` findest du Briefe nach Absender, Betreff, Aktenzeichen oder Wörtern im Text, mit `read_document` liest du einen ganz, samt den anderen Briefen desselben Vorgangs.
- Soll ein Brief weitergegeben werden, etwa als Anhang einer Mail, holst du mit `document_file` das Original (den Scan als PDF oder das Foto) in deine Arbeitsmappe. Verschickt wird immer das Original, nie die Textfassung aus dem Firmengedächtnis. Für vertrauliche Briefe gibt es `confidential_document_file`.
- `due_dates` zeigt, was in den nächsten Tagen fällig ist. Vertrauliche Briefe stehen dort nur mit Art und Datum.
- Briefe vom Gericht oder Anwalt sind immer vertraulich und gehen nur an den Inhaber.
- Steht ein Brief auf „prüfen“, ist etwas unklar, meist eine Frist: nenne dann nie ein Datum, sondern sag, dass jemand im Brief nachsehen muss. Wer nachgesehen hat, bestätigt das auf der Seite „Post“ unter „Zu prüfen“ mit „Geprüft“ und trägt dabei die Frist ein, falls der Brief eine nennt; danach ist der Brief abgelegt.
- Für die Buchhaltung liefert `receipt_data` Absender, Nummer, Betrag, IBAN und Verwendungszweck eines Belegs. Wurde bei einem Beleg der Betrag, der Absender oder das Datum nicht erkannt, kommt er nicht als Beleg in die Buchhaltung, sondern steht auf „prüfen“.
- Ältere Briefe, die beim ersten Abholen eines Scanner-Ordners schon dort lagen, werden nur abgelegt: Sie sind auffindbar, ihre Fristen stehen in `due_dates`, aber daraus entsteht keine Aufgabe.

## Einrichten (Recht „Post einrichten“, meist beim IT-Betreuer)

Der Scanner oder das NAS, auf das er scannt, legt die Briefe in einen SFTP- oder FTPS-Ordner, der aus dem Internet erreichbar ist. Seine Zugangsdaten kommen als Tresor-Eintrag der Art Dateiablage mit dem Namen `SCANNER` (weitere als `SCANNER2` …), der Schlüssel für die Texterkennung als Eintrag `OCR`. Danach zeigt `sources_status`, ob jede Ablage antwortet und ob die Texterkennung einen Schlüssel hat; `sync_now` holt sofort ab, im Hintergrund, und eine Minute später sagt `sources_status`, ob es geklappt hat. Zeigt ein SFTP-Server plötzlich einen anderen Schlüssel, wird aus Vorsicht nichts abgeholt: frag den Inhaber, ob der Server neu eingerichtet wurde; dann nimmt er den neuen Schlüssel auf der Seite „Post“ an. Hochladen vom Handy geht immer, auch ganz ohne Scanner.
