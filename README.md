# vilikon-dms

Paper post for Vilikon: letters, tax notices, court and attorney documents and invoices arrive from a file store (the
scanner's SFTP/FTPS folder; SMB, Google Drive and OneDrive later) or as phone photos. The DMS reads them with Mistral
OCR and document annotation, files them by case, keeps due dates and tells the cockpit what someone has to do.

It is a **Vilikon Werkzeug** (tool app): its own repository and version (`VERSION`), installed by the IT Specialist from
the adapter catalog and run by the core's Verwalter in the shared tools container. It speaks the core's standards
`vilikon.adapter/1`, `vilikon.modul/1` and `vilikon.wissen/1` (in the core repo: `docs/ADAPTER-PLAN.md`,
`backend/app/schnittstellen/modul_*.md`, `wissen_*.md`). It also runs standalone as a container.

**Calls go only from the cockpit to the DMS.** The DMS never reaches the cockpit's database or backend; the cockpit
polls events and the file list, the Verwalter hands it the released credentials as environment variables. The DMS
itself reaches out only to the customer's file stores and to Mistral.

All code, JSON fields of the DMS's own API, database columns and environment variables are English. Only what the
core's standards define keeps its names: the MODULE.json keys (`schluessel`, `rechte`, `funktionen`, `ereignisse`,
`karten`, `anschluesse`, …), the paths `ki/protokoll`, `ki/ereignisse`, `ki/karten/…`, `ki/pruefen`,
`ki/wissen/dateien|datei` with their fields, the Verwalter's variables (`<NAME>_ART`, `<NAME>_PASSWORT`,
`OCR_BETREIBER`), and errors as `{"fehler": "…"}`. Texts people read are German or US English (`app/texts/de.py`,
`en.py`; German is the source, a test keeps both in step).

## As a Werkzeug

The core reads three files from the released repository:

| File | |
|---|---|
| `ADAPTER.json` | `vilikon.adapter/1`: slug `dms`, build and start, the check `ki/pruefen`, the setup text, the two credentials `OCR` (vault entry of type `api_key`, the operator may provide a Mistral key) and `SCANNER` (type `filestore`, optional), and which files to swap for English |
| `MODULE.json` | `vilikon.modul/1` in German; `vilikon/en/MODULE.json` in English. Generated: `python -m app.module --write` (a test fails if they are stale) |
| `BRIEFING.md` | What every employee with access learns about the DMS; `vilikon/en/BRIEFING.md` in English |

The Verwalter builds with `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (Python 3.11 or newer,
no `pip install .`) and starts `.venv/bin/python -m app` in the repository with a clean environment. The page is
reached through Caddy at `/werkzeug/dms/` (prefix stripped) behind the cockpit's login; the browser never reaches `ki/`.

The tools share one container with 1 GB of memory, so the DMS puts a letter together from photos one page at a time
and keeps one letter at a time on its way to the OCR. Temporary files (spooled uploads) go below `DATA_DIR/tmp`.

## Standalone

```bash
docker build -t vilikon-dms .
docker run -e DMS_TOKEN=… -e MISTRAL_API_KEY=… -v dms-data:/data -p 8090:8090 vilikon-dms
```

`ki/` calls then need `Authorization: Bearer $DMS_TOKEN`; the page needs a proxy in front that sets the headers the
core's Caddy would (see [Page and phone](#page-and-phone)).

## Environment

| Variable | Default | |
|---|---|---|
| `PORT`, `HOST` | `8090`, `127.0.0.1` (`0.0.0.0` in the image) | Set by the Verwalter |
| `DATA_DIR` | `data` (`/data` in the image) | SQLite `dms.sqlite3`, originals in `originals/`, temporary files in `tmp/`. No secrets are stored there |
| `VILIKON_TOKEN` | – | The per-tool token from the Verwalter; every `ki/` call and every page request carries it as `X-Vilikon-Token` |
| `VILIKON_LANGUAGE` | `de` | `de` or `en`, fixed per instance like the cockpit's. Falls back to `DMS_LANGUAGE` |
| `OCR_ART`, `OCR_SERVICE`, `OCR_PASSWORT` | – | The vault entry `OCR`: type `api_key`, service `mistral`, the key. Falls back to `MISTRAL_API_KEY`. Without a key documents wait |
| `OCR_BETREIBER` | – | `ja`: the key is the operator's, so the page cap applies. A customer's own key comes without it: no cap |
| `OCR_PAGES_PER_MONTH` | `500` | Pages per calendar month on the operator's key; `0` = no cap. Falls back to `DMS_PAGES_PER_MONTH` |
| `SCANNER_ART` | – | `filestore`: this prefix is a file store. Every prefix with `<NAME>_ART=filestore` is one (`SCANNER2_*` …), read on every pass |
| `SCANNER_PROTOCOL` | – | `sftp`, `ftps` or `ftp` (plain, no TLS) |
| `SCANNER_HOST`, `SCANNER_PORT`, `SCANNER_USER`, `SCANNER_PASSWORT` | – | Where and as whom; the port defaults to 22 (SFTP) or 21 |
| `SCANNER_FOLDER` | – | The folder the scanner writes into |
| `SCANNER_MOVE_DONE` | – | `true`, `1` or `ja`: move fetched files into the subfolder `done/`; otherwise the store is only read |
| `DMS_TOKEN` | – | Standalone: `ki/` needs `Authorization: Bearer <token>`. With neither token set everything but `/health` is refused |
| `DMS_LANGUAGE`, `MISTRAL_API_KEY`, `DMS_PAGES_PER_MONTH` | – | Standalone stand-ins, see above |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | |
| `DMS_INTERVAL_MIN` | `10` | How often the file stores are fetched (the first pass about 5 s after the start); `0` = only on `POST ki/sync` |

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

All `ki/` endpoints need `X-Vilikon-Token: $VILIKON_TOKEN` (or, standalone, `Authorization: Bearer $DMS_TOKEN`); the
employee calling is in `X-Vilikon-Mitarbeiter`. Errors are `{"fehler": "…"}` with status 4xx/5xx in plain words.
`GET /health` needs nothing.

### vilikon.modul/1

The module describes itself in `MODULE.json` and `BRIEFING.md` (no `ki/modul`, no `ki/anleitung`).

| Method | Path | Answer |
|---|---|---|
| GET | `ki/protokoll?seit=&bis=` | `[{zeit, wer, was}]` |
| GET | `ki/ereignisse?seit=` | `{"ereignisse": [{id, art, titel, text, time, data}]}`, at most 5 |
| GET | `ki/karten/mail` | Card: letters to review and due dates of the next 10 days |
| GET | `ki/karten/pages` | Card: pages this month, cap, waiting documents, one line per failing file store |
| GET | `ki/pages` | `{month, pages, cap, own_key, waiting}` for the operator's pulse |
| GET | `ki/pruefen` | The check: `{ok, text, sources: [{id, protocol, host, ok, error, last_fetch}], ocr: {ok, operator, pages_used, cap}}`. Lists every store's folder (10 s each); `ok` is false without an OCR key or when a store fails |
| POST | `ki/sync` | `202 {"status": "started" \| "running", "text"}`: fetch and read now, in the background, under the same lock as the timed passes |

Rights: `read` (not sensitive), `confidential` (sensitive), `receipts`, `setup` (sensitive: “Post einrichten” / “Set up
the mail”, usually the IT Specialist's).

| Function | Right | Path |
|---|---|---|
| `search_documents` | read | GET `ki/documents?query=&kind=&from=&to=` (no confidential documents) |
| `read_document` | read | GET `ki/documents/{id}`: text, due dates, the other documents of the case |
| `search_confidential_documents` | confidential | GET `ki/confidential/documents?…` |
| `read_confidential_document` | confidential | GET `ki/confidential/documents/{id}` |
| `due_dates` | read | GET `ki/due_dates?from=&to=` (default today + 10 days); confidential ones only with kind and date |
| `receipt_data` | receipts | GET `ki/receipts/{id}`: sender, date, number, amount, IBAN, payment reference, `file` (GET `ki/receipts/{id}/file`, the original) |
| `sources_status` | setup | GET `ki/pruefen` |
| `sync_now` | setup | POST `ki/sync` |

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

### vilikon.wissen/1 (`anschluesse` in MODULE.json)

| Method | Path | Answer |
|---|---|---|
| GET | `ki/wissen/dateien` | `{"dateien": [{id, name, pfad, version, groesse, sensibel, meta}]}` – the whole list, documents in `done` or `review` |
| GET | `ki/wissen/datei?id=` | The document as Markdown (`text/markdown`): title, fields, due dates, then the OCR text |

Extensions to the standard: per-file `sensibel` (the standard's own flag, here per confidential document) and `meta`
(`kind, sender, date, file_number, action, due_dates[], status`). Files are Markdown, so the cockpit does not run OCR a
second time.

### File stores

They come only from the environment (`SCANNER_*`, see above), never through the API, and are read anew on every
pass. The store keeps per store only its last error, the time of the last fetch and the SFTP host key: on first
contact the key is trusted and kept for that host and port; if it changes, nothing is fetched and the error says so
until the owner accepts the new key on the page. Unknown protocols (`smb`, `gdrive`, `onedrive`) answer "not supported
yet". Version 0.1.0 kept pushed sources and the customer's key in the store; 0.2.0 deletes them on its first start.

### Page and phone

`GET /` (menu entry „Post“ / "Mail", `/werkzeug/dms/` from outside): the inbox, the review list, the page count and an
upload form for phone photos; for the owner also the file stores with their errors, a "Fetch now" button
(`POST /api/sync`) and, after a changed SFTP host key, a button to accept it (`POST /api/sources/{id}/trust`).
`GET /api/documents` feeds it.

The page and `/api/*` need `X-Vilikon-Token` and `X-Vilikon-Benutzer` (email), both set by the core's Caddy.
Confidential letters and the owner's buttons only with `X-Vilikon-Owner: 1` (not by `X-Vilikon-Rolle`: the owner who
set up the instance has the role `betreiber`).

`POST /api/upload` (multipart, field `files`, up to 30 images or one PDF): the pages become one PDF and are read at once.
Answer `{id, duplicate, status, text}`. At most 20 MB per file, 60 MB per letter (refused by `Content-Length` before
the body is read) and 40 megapixels per photo.

## Development

No containers on the development machine. Tests run on the server in a throw-away container, under Python 3.11 and
3.12 like the CI:

```bash
tar --exclude .git --exclude .venv -czf - . | ssh vilikon-vps 'rm -rf ~/dms-test && mkdir ~/dms-test && tar -xzf - -C ~/dms-test'
ssh vilikon-vps 'for v in 3.11 3.12; do docker run --rm -v ~/dms-test:/src:ro -w /src -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:$v-slim sh -c "pip install -q uv==0.13.9 && uv sync --frozen && uv run ruff check --no-cache . && uv run ruff format --check --no-cache . && uv run pytest -q -p no:cacheprovider"; done'
```

- Dependencies live in `pyproject.toml` and `uv.lock`; `requirements.txt` (what the Verwalter installs) comes from
  `uv export --frozen --no-dev --no-emit-project -o requirements.txt`. The CI fails if it is stale.
- After changing rights, functions, events, cards or their texts: `python -m app.module --write`.
- A new version: `VERSION`, `ADAPTER.json` `version`, `python -m app.module --write`, `CHANGELOG.md` + `CHANGELOG.en.md`
  (a test keeps them in step).

Tests use only invented data: a fake cockpit (`tests/conftest.py: FakeCockpit`, calling like the core does), fake
SFTP/FTP stores, and recorded Mistral answers for three invented letters (`tests/fixtures/mistral/`: an invoice from
Musterfirma GmbH, a tax notice from Finanzamt Musterstadt, advertising).
