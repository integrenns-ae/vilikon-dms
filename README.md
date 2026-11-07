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

## Running

| Variable | Default | |
|---|---|---|
| `DMS_TOKEN` | – | Service token. Every `ki/` call needs `Authorization: Bearer <token>`. Empty: all `ki/` calls are refused. Generated per instance by the core's `deploy.sh`/`neuer-kunde.sh` (credstore entry `<slug>-env`). |
| `DATA_DIR` | `data` (`/data` in the image) | SQLite `dms.sqlite3`, originals in `originale/`. Holds the credentials pushed by the cockpit: a volume of its own, never shared. |
| `DMS_SPRACHE` | `de` | `de` or `en`, fixed per instance like the cockpit's. |
| `MISTRAL_API_KEY` | – | The operator's key. Without any key documents wait. |
| `MISTRAL_OCR_MODEL` | `mistral-ocr-latest` | |
| `DMS_SEITEN_MONAT` | `500` | Pages per calendar month on the operator's key; `0` = no cap. |
| `DMS_INTERVALL_MIN` | `10` | How often the file stores are fetched; `0` = only on `POST ki/abgleich`. |

The cockpit calls the DMS at `http://dms:8090`. The browser reaches it through Caddy at `/modul/dms/` (prefix stripped,
`X-Forwarded-Prefix: /modul/dms`) behind the cockpit's login: `forward_auth` adds the token, `X-Vilikon-Benutzer`
(email) and `X-Vilikon-Rolle` (`kunde` = owner, `betreiber` = operator), and never forwards `ki/…` from the browser.
The port must stay on the internal network. The image runs with a read-only root file system: it writes only to
`DATA_DIR` and `/tmp` (tmpfs).

## Flow

```
file store / phone ─► intake ─► sha256 dedupe ─► page budget ─► Mistral OCR + annotation ─► rules ─► store
                                                    │ (cap reached: status "wartet")                │
                                                    └──────── next month, oldest first ◄────────────┘
store ─► ki/wissen/* (company memory)   ki/ereignisse (cases)   ki/karten/* (dashboard)   functions (employees)
```

Document status: `neu`, `wartet` (page cap or no key; `grund` says which), `fertig`, `pruefen` (a person must look),
`fehler`. Fixed rules after Mistral's answer (`app/ocr.py: normalise`):

- court (`gericht`) and attorney (`anwalt`) documents are always confidential, and their event is for the owner only
  (`daten.nur_inhaber`);
- a due date is taken only if Mistral read an exact printed date (`sicher: true`, valid ISO date); otherwise the
  document goes to `pruefen` and no date is stored – never guessed. A court/attorney letter that demands something
  but shows no deadline goes to `pruefen` as well;
- an IBAN with a wrong checksum is dropped and the document goes to `pruefen`;
- advertising asks for nothing: no events, no due dates; it is still filed;
- more than 8 pages: OCR without annotation (Mistral's limit), status `pruefen`.

Cases: documents with the same file number (Aktenzeichen, tax number, invoice number; normalised) share a `fall_id`,
so a reminder sits with its invoice and an objection with its notice.

## Contract

All `ki/` endpoints: `Authorization: Bearer $DMS_TOKEN`; the employee calling is in `X-Vilikon-Mitarbeiter`. Errors
are `{"fehler": "…"}` with status 4xx/5xx in plain words.

### vilikon.modul/1

| Method | Path | Answer |
|---|---|---|
| GET | `ki/modul` | The MODUL.json (in the instance's language): rights, functions, events, cards, `anschluesse` |
| GET | `ki/anleitung` | Instruction for employees (text) |
| GET | `ki/protokoll?seit=&bis=` | `[{zeit, wer, was}]` |
| GET | `ki/ereignisse?seit=` | `{"ereignisse": [{id, art, titel, text, zeit, daten}]}`, at most 5 |
| GET | `ki/karten/post` | Card: letters to check and due dates of the next 10 days |
| GET | `ki/karten/seiten` | Card: pages this month, cap, waiting documents |
| GET | `ki/seiten` | `{monat, seiten, grenze, eigener_schluessel, wartend}` for the operator's pulse |

Rights: `lesen` (not sensitive), `vertraulich` (sensitive), `belege`.

| Function | Right | Path |
|---|---|---|
| `dokument_suchen` | lesen | GET `ki/dokumente?suche=&art=&von=&bis=` (no confidential documents) |
| `dokument_lesen` | lesen | GET `ki/dokumente/{id}`: text, due dates, the other documents of the case |
| `vertrauliche_dokumente_suchen` | vertraulich | GET `ki/vertraulich/dokumente?…` |
| `vertrauliches_dokument_lesen` | vertraulich | GET `ki/vertraulich/dokumente/{id}` |
| `fristen` | lesen | GET `ki/fristen?von=&bis=` (default today + 10 days); confidential ones only with kind and date |
| `beleg_daten` | belege | GET `ki/belege/{id}`: sender, date, number, amount, IBAN, reference, `datei` (GET `ki/belege/{id}/datei`, the original) |

Events (`art`), each `daten` carrying `dokument_id, art, absender, betreff, datum, aktenzeichen, handlung, betrag,
iban, verwendungszweck, fristen[], vertraulich, fall_id, status, grund, nur_inhaber`:

| art | When |
|---|---|
| `zahlen`, `antworten`, `widersprechen`, `frist` | The letter demands this; its due dates are in `daten.fristen` |
| `frist_neu` | One per due date of a letter that demands nothing else (`daten.frist`) |
| `gericht` | Every court or attorney document, for the owner only |
| `pruefen` | Something is unclear (`daten.grund`) |
| `beleg` | Invoice or receipt for the bookkeeping (also besides `zahlen`) |
| none | Advertising |

The core takes at most 5 events per fetch and moves `seit` to the time of its fetch. So the DMS returns events not yet
handed out first, then those newer than `seit`; ids repeat harmlessly (the core takes each id once).

### vilikon.wissen/1 (`anschluesse` in `ki/modul`)

| Method | Path | Answer |
|---|---|---|
| GET | `ki/wissen/dateien` | `{"dateien": [{id, name, pfad, version, groesse, sensibel, meta}]}` – the whole list, documents in `fertig` or `pruefen` |
| GET | `ki/wissen/datei?id=` | The document as Markdown (`text/markdown`): title, fields, due dates, then the OCR text |

Extensions to the standard: per-file `sensibel` (confidential documents) and `meta` (`art, absender, datum,
aktenzeichen, handlung, fristen[], status`). Files are Markdown, so the cockpit does not run OCR a second time.

### Sources

| Method | Path | |
|---|---|---|
| PUT | `ki/quellen` | `{"quellen": [{id, art, host, port, user, passwort, ordner, verschieben, tls, aktiv}], "mistral_schluessel"?}` – all sources at once; missing ones are removed. `mistral_schluessel`: the customer's own key (lifts the page cap), `""` removes it |
| GET | `ki/quellen` | Sources without secrets, with `fehler` and `letzter_abruf`, plus the page state |
| POST | `ki/abgleich` | Fetch and read now; counts `{neu, doppelt, fehler, gelesen}` |

`art`: `sftp`, `ftp` (FTPS unless `tls: false`); `smb`, `gdrive`, `onedrive` answer "not supported yet". Stores are
read only, unless `verschieben: true` moves done files into the subfolder `erledigt/`.

### Page and phone

`GET /` (menu entry „Post“ / "Mail", `/modul/dms/` from outside): the inbox, the „prüfen“ list, the page count and an
upload form for phone photos. `GET /api/dokumente` feeds it; confidential letters only for the role `kunde`.

`POST /api/upload` (`/modul/dms/api/upload` from outside) (multipart, field `dateien`, several images or one PDF): the pages become one PDF and are read at
once. Answer `{id, doppelt, status, text}`. Needs the token or `X-Vilikon-Benutzer` from Caddy's forward_auth.

## Development

No containers on the development machine. Tests run on the server in a throw-away container:

```bash
tar --exclude .git -czf - . | ssh vilikon-vps 'rm -rf ~/dms-test && mkdir ~/dms-test && tar -xzf - -C ~/dms-test'
ssh vilikon-vps 'docker run --rm -v ~/dms-test:/src -w /src -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim sh -c "pip install -q uv && uv sync --frozen && uv run ruff check . && uv run ruff format --check . && uv run pytest -q"'
```

Tests use only invented data: a fake cockpit (`tests/conftest.py: FakeCockpit`, calling like the core does), fake
SFTP/FTP stores, and recorded Mistral answers for three invented letters (`tests/fixtures/mistral/`: an invoice from
Musterfirma GmbH, a tax notice from Finanzamt Musterstadt, advertising).

Texts people read are in `app/texte/dms_de.py` and `dms_en.py`; German is the source, a test keeps both in step.
