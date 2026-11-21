What for: the company's paper mail. Letters, notices, invoices and court mail arrive from the scanner or as a photo from the phone, are read, filed by case, and their due dates found.

- `search_documents` finds letters by sender, subject, file number or words in the text, `read_document` reads one in full, with the other letters of the same case.
- `due_dates` shows what is due in the next days. Confidential letters appear there with kind and date only.
- Letters from a court or an attorney are always confidential and go to the owner only.
- If a letter is marked “check”, something is unclear, usually a due date: never name a date then, say that someone has to look at the letter.
- For the bookkeeping, `receipt_data` gives a receipt's sender, number, amount, IBAN and payment reference.

## Setting it up (right “Set up the mail”, usually with the IT Specialist)

The scanner, or the NAS it scans to, puts the letters into an SFTP or FTPS folder reachable from the internet. Its credentials come as a vault entry of type file store named `SCANNER` (more as `SCANNER2` …), the key for text recognition as the entry `OCR`. Then `sources_status` shows whether every file store answers and whether text recognition has a key; `sync_now` fetches at once, in the background, and a minute later `sources_status` tells whether it worked. If an SFTP server suddenly shows a different key, nothing is fetched to be safe: ask the owner whether the server was set up anew; then they accept the new key on the “Mail” page. Uploading from the phone always works, even without any scanner.
