# vilikon-dms

Paper post for Vilikon: letters, tax notices, court and attorney documents and invoices arrive from a file store (the
scanner's SFTP/FTP folder; SMB, Google Drive and OneDrive later) or as phone photos. The DMS reads them with Mistral
OCR and document annotation, files them by case, keeps due dates and tells the cockpit what someone has to do.

It is a **product module**: its own repository, its own version (`VERSION`), its own container `dms` (port 8090,
`mem_limit: 512m`), pinned per Vilikon release. It speaks the core's standards `vilikon.modul/1` and `vilikon.wissen/1`
(in the core repo: `backend/app/schnittstellen/modul_*.md`, `wissen_*.md`).

**Calls go only from the cockpit to the DMS.** The DMS never reaches the cockpit's database or backend; the cockpit
polls events and the file list and pushes source settings and credentials. The DMS itself reaches out only to the
customer's file stores and to Mistral.

All code, JSON fields of the DMS's own API, database columns and environment variables are English. Only what the
core's standards define keeps its names: the MODUL.json keys (`schluessel`, `rechte`, `funktionen`, `ereignisse`,
`karten`, `anschluesse`, …), the paths `ki/modul`, `ki/anleitung`, `ki/protokoll`, `ki/ereignisse`, `ki/karten/…`,
`ki/wissen/dateien|datei` with their fields, and errors as `{"fehler": "…"}`. Texts people read are German or US
English (`app/texts/de.py`, `en.py`; German is the source, a test keeps both in step).

## Running

| Variable | Default | |
|---|---|---|
| `DMS_TOKEN` | – | Service token. Every `ki/` call needs `Authorization: Bearer <token>`. Empty: all `ki/` calls are refused. Generated per instance by the core's `deploy.sh`/`neuer-kunde.sh`. |
| `DATA_DIR` | `data` (`/data` in the image) | SQLite `dms.sqlite3`, originals in `originals/`. Holds the credentials pushed by the cockpit: a volume of its own, never shared. |
| `DMS_LANGUAGE` | `de` | `de` or `en`, fixed per instance like the cockpit's. |
| `MISTRAL_API_KEY` | – | The operator's key. Without any key documents wait. |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | |
| `DMS_PAGES_PER_MONTH` | `500` | Pages per calendar month on the operator's key; `0` = no cap. |
| `DMS_INTERVAL_MIN` | `10` | How often the file stores are fetched; `0` = only on `POST ki/sync`. |

The cockpit calls the DMS at `http://dms:8090`. The browser reaches it through Caddy at `/modul/dms/` (prefix stripped,
`X-Forwarded-Prefix: /modul/dms`) behind the cockpit's login: `forward_auth` adds the token, `X-Vilikon-Benutzer`
(email) and `X-Vilikon-Rolle` (`kunde` = owner, `betreiber` = operator), and never forwards `ki/…` from the browser.
The port must stay on the internal network. The image runs with a read-only root file system: it writes only to
`DATA_DIR` and `/tmp` (tmpfs). Health check: `GET /health` (no token).

## Flow

```
file store / phone ─► intake ─► sha256 dedupe ─► page budget ─► Mistral OCR + annotation ─► rules ─► store
                                                    │ (cap reached: status "waiting")               │
                                                    └──────── next month, oldest first ◄────────────┘
store ─► ki/wissen/* (company memory)   ki/ereignisse (cases)   ki/karten/* (dashboard)   functions (employees)
```

Document status: `new`, `waiting` (page cap or no key; `reason` says which), `done`, `review` (a person must look),
`error`. Kinds: `letter, notice, invoice, reminder, contract, court, attorney, advertising, other`. Actions:
`pay, reply, object, deadline, none`. Due date kinds: `payment, tax, objection, reply, court, attorney, appointment,
other`.

Fixed rules after Mistral's answer (`app/ocr.py: normalise`):

- court and attorney documents are always confidential, and their event is for the owner only (`data.owner_only`);
- a due date is taken only if Mistral read an exact printed date (`certain: true`, valid ISO date); otherwise the
  document goes to `review` and no date is stored – never guessed. A court/attorney letter that demands something but
  shows no deadline goes to `review` as well;
- an IBAN with a wrong checksum is dropped and the document goes to `review`;
- advertising asks for nothing: no events, no due dates; it is still filed;
- more than 8 pages: OCR without annotation (Mistral's limit), status `review`.

Cases: documents with the same file number (Aktenzeichen, tax number, invoice number; normalised) share a `case_id`,
so a reminder sits with its invoice and an objection with its notice.

## Contract

All `ki/` endpoints: `Authorization: Bearer $DMS_TOKEN`; the employee calling is in `X-Vilikon-Mitarbeiter`. Errors
are `{"fehler": "…"}` with status 4xx/5xx in plain words.

### vilikon.modul/1

| Method | Path | Answer |
|---|---|---|
| GET | `ki/modul` | The MODUL.json (in the instance's language): rights, functions, events, cards, `menue`, `anschluesse` |
| GET | `ki/anleitung` | Instruction for employees (text) |
| GET | `ki/protokoll?seit=&bis=` | `[{zeit, wer, was}]` |
| GET | `ki/ereignisse?seit=` | `{"ereignisse": [{id, art, titel, text, time, data}]}`, at most 5 |
| GET | `ki/karten/mail` | Card: letters to review and due dates of the next 10 days |
| GET | `ki/karten/pages` | Card: pages this month, cap, waiting documents |
| GET | `ki/pages` | `{month, pages, cap, own_key, waiting}` for the operator's pulse |

Rights: `read` (not sensitive), `confidential` (sensitive), `receipts`.

| Function | Right | Path |
|---|---|---|
| `search_documents` | read | GET `ki/documents?query=&kind=&from=&to=` (no confidential documents) |
| `read_document` | read | GET `ki/documents/{id}`: text, due dates, the other documents of the case |
| `search_confidential_documents` | confidential | GET `ki/confidential/documents?…` |
| `read_confidential_document` | confidential | GET `ki/confidential/documents/{id}` |
| `due_dates` | read | GET `ki/due_dates?from=&to=` (default today + 10 days); confidential ones only with kind and date |
| `receipt_data` | receipts | GET `ki/receipts/{id}`: sender, date, number, amount, IBAN, payment reference, `file` (GET `ki/receipts/{id}/file`, the original) |

Events (`art`), each `data` carrying `document_id, kind, sender, subject, date, file_number, action, amount, iban,
payment_reference, due_dates[], confidential, case_id, status, reason, owner_only`:

| art | When |
|---|---|
| `pay`, `reply`, `object`, `deadline` | The letter demands this; its due dates are in `data.due_dates` |
| `new_due_date` | One per due date of a letter that demands nothing else (`data.due_date`) |
| `court` | Every court or attorney document, for the owner only |
| `review` | Something is unclear (`data.reason`) |
| `receipt` | Invoice or receipt for the bookkeeping (also besides `pay`) |
| none | Advertising |

The core takes at most 5 events per fetch and moves `seit` to the time of its fetch. So the DMS returns events not yet
handed out first, then those newer than `seit`; ids repeat harmlessly (the core takes each id once).

### vilikon.wissen/1 (`anschluesse` in `ki/modul`)

| Method | Path | Answer |
|---|---|---|
| GET | `ki/wissen/dateien` | `{"dateien": [{id, name, pfad, version, groesse, sensibel, meta}]}` – the whole list, documents in `done` or `review` |
| GET | `ki/wissen/datei?id=` | The document as Markdown (`text/markdown`): title, fields, due dates, then the OCR text |

Extensions to the standard: per-file `sensibel` (the standard's own flag, here per confidential document) and `meta`
(`kind, sender, date, file_number, action, due_dates[], status`). Files are Markdown, so the cockpit does not run OCR a
second time.

### Sources

| Method | Path | |
|---|---|---|
| PUT | `ki/sources` | `{"sources": [{id, kind, host, port, user, password, folder, move_done, tls, active}], "mistral_key"?}` – all sources at once; missing ones are removed. `mistral_key`: the customer's own key (lifts the page cap), `""` removes it |
| GET | `ki/sources` | Sources without secrets, with `error` and `last_fetch`, plus the page state |
| POST | `ki/sync` | Fetch and read now; counts `{new, duplicate, errors, read}` |

`kind`: `sftp`, `ftp` (FTPS unless `tls: false`); `smb`, `gdrive`, `onedrive` answer "not supported yet". Stores are
read only, unless `move_done: true` moves done files into the subfolder `done/`.

### Page and phone

`GET /` (menu entry „Post“ / "Mail", `/modul/dms/` from outside): the inbox, the review list, the page count and an
upload form for phone photos. `GET /api/documents` feeds it; confidential letters only for the role `kunde`.

`POST /api/upload` (`/modul/dms/api/upload` from outside; multipart, field `files`, several images or one PDF): the
pages become one PDF and are read at once. Answer `{id, duplicate, status, text}`. Needs the token or
`X-Vilikon-Benutzer` from Caddy's forward_auth.

## Development

No containers on the development machine. Tests run on the server in a throw-away container:

```bash
tar --exclude .git -czf - . | ssh vilikon-vps 'rm -rf ~/dms-test && mkdir ~/dms-test && tar -xzf - -C ~/dms-test'
ssh vilikon-vps 'docker run --rm -v ~/dms-test:/src -w /src -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim sh -c "pip install -q uv && uv sync --frozen && uv run ruff check . && uv run ruff format --check . && uv run pytest -q"'
```

Tests use only invented data: a fake cockpit (`tests/conftest.py: FakeCockpit`, calling like the core does), fake
SFTP/FTP stores, and recorded Mistral answers for three invented letters (`tests/fixtures/mistral/`: an invoice from
Musterfirma GmbH, a tax notice from Finanzamt Musterstadt, advertising).
