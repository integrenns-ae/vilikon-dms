# Changelog

## Unreleased

## 0.2.0

- Mail is now a tool app: the IT Specialist installs it from the catalog, without a container of its own.
- Credentials come from the vault: the scanner folder as the entry `SCANNER` of type file store (more as `SCANNER2` …),
  the key for text recognition as the entry `OCR`. Mail itself no longer stores any password, and on its first start it
  deletes what earlier versions had stored.
- The operator's key has a set number of pages per month. An own Mistral key has no cap.
- New right “Set up the mail”: whoever has it sees whether every file store answers and whether text recognition has a
  key, and can have the mail fetched at once.
- Fetching runs in the background, the first time a few seconds after the start. The “Mail: pages” card shows which file
  store is not answering.
- On the “Mail” page the owner sees the file stores and can fetch at once.
- SFTP stores are recognised by their key. If the server suddenly shows a different one, Mail fetches nothing until the
  owner accepts the new key on the page.
- Only the owner sees confidential letters; Mail now checks this correctly.
- Photos from the phone need much less memory: the pages are put together one at a time. At most 60 MB per letter and
  40 megapixels per photo.

## 0.1.0

- Mail from the file store: the scanner puts letters into an SFTP or FTP folder, the module fetches them, reads them
  with Mistral and files them. The same letter twice is read only once.
- Mail from the phone: several photos of one letter become one PDF.
- Recognised are kind, sender, date, file number, what has to be done, due dates, amount, IBAN and payment reference,
  whether it is a receipt and whether it is confidential. Mail from a court or an attorney is always confidential and
  goes to the owner only; an unclear due date is never guessed, the letter is marked “check”.
- Letters with the same file number form a case.
- A page of its own in the menu “Mail”: inbox, the “check” list and uploading from the phone. Only the owner sees
  confidential letters.
- Page cap per month (default 500 pages); beyond it, letters wait until the start of the month. An own Mistral key
  lifts it.
- Connection to the cockpit: company memory (confidential letters stay confidential), events for tasks, two cards,
  functions for searching, for due dates and for receipt data.
