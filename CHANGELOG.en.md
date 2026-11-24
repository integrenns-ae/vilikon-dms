# Changelog

## Unreleased

## 0.4.0

- Employees with the right “See mail” fetch a letter's original (the scan or the photo) into their work folder and
  can attach it to a mail; confidential letters need “See confidential mail”. The file is named after date and sender.

## 0.3.0

- The “Mail” page now looks like the cockpit: the same colours, type, cards and buttons, on the phone and in dark
  mode too. When the owner changes the cockpit's colour, it follows.
- “To check” and “Inbox” as tabs with counts; kind, status and “confidential” are small labels on each letter.
- A click on a letter opens it, so an unclear date can be checked in the letter right away. Only the owner opens
  confidential letters.
- Choosing photos or a PDF uploads the letter at once, without a second button.

## 0.2.2

- When a scanner folder is fetched for the first time, older letters that already lay there (dated more than 30 days
  before the fetch) are only filed: they can be found and their due dates are kept, but they no longer become tasks and
  cases for the owner.
- A date that has already passed no longer becomes a new due date in the calendar.
- When Mail does not recognise a receipt's amount, sender or date, the letter is now marked “check” and says what is
  missing. Until now such a receipt was silently lost instead of reaching the bookkeeping.

## 0.2.1

- When Mail does not read a letter from the phone, the answer now says why: for example that it has more pages than
  may be read in a month, or that this month's pages are used up.

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
