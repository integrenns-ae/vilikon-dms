"""The DMS service. Only the cockpit calls `ki/…`, with the service token (vilikon.modul/1, vilikon.wissen/1). People
reach `/` and `/api/…` through Caddy at /modul/dms/, behind the cockpit's login. The DMS never calls the cockpit.

Keys and paths the core's standards define stay as they are there (`ki/modul`, `ki/ereignisse`, `ki/wissen/…`,
`{"fehler": …}`, the card fields); everything else is the DMS's own and English."""

from __future__ import annotations

import hmac
import html
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException

from app import VERSION, budget, config, intake, pipeline
from app.module import describe
from app.store import Store
from app.texts import t
from app.upload import UploadError, to_pdf

log = logging.getLogger(__name__)

MAX_EVENTS = 5  # the cockpit takes at most this many per fetch
FILED = ("done", "review")
_store: Store | None = None
_store_lock = threading.Lock()
_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None or _store.data_dir != config.settings.data_dir:
            _store = Store(config.settings.data_dir)
        return _store


class Refusal(Exception):
    def __init__(self, status: int, text: str) -> None:
        self.status, self.text = status, text


def _loop(stop: threading.Event) -> None:
    while not stop.wait(max(1, config.settings.intake_interval_min) * 60):
        try:
            pipeline.intake_pass(get_store())
        except Exception:
            log.exception("intake pass failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    if config.settings.intake_interval_min > 0:
        threading.Thread(target=_loop, args=(stop,), daemon=True, name="intake").start()
    yield
    stop.set()


app = FastAPI(title="vilikon-dms", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(Refusal)
async def _refusal(request: Request, e: Refusal) -> JSONResponse:
    return JSONResponse({"fehler": e.text}, status_code=e.status)


@app.exception_handler(HTTPException)
async def _http(request: Request, e: HTTPException) -> JSONResponse:
    text = t("error.path") if e.status_code in (404, 405) else str(e.detail)
    return JSONResponse({"fehler": text}, status_code=e.status_code)


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, e: RequestValidationError) -> JSONResponse:
    where = ", ".join(".".join(str(x) for x in err.get("loc", ())[1:]) for err in e.errors()[:3])
    return JSONResponse({"fehler": t("error.input", error=where)}, status_code=400)


def _token_ok(request: Request) -> bool:
    token = config.settings.token
    given = request.headers.get("authorization", "")
    return bool(token) and hmac.compare_digest(given.encode(), f"Bearer {token}".encode())


def cockpit(request: Request) -> str:
    """Every ki/ call: the service token, or nothing. Returns who asks (the employee, or `cockpit`)."""
    if not _token_ok(request):
        raise Refusal(401, t("error.token"))
    return request.headers.get("x-vilikon-mitarbeiter") or "cockpit"


def person(request: Request) -> str:
    """The page and the phone upload, reached as /modul/dms/… through Caddy: the cockpit's forward_auth has checked the
    login and sends the token with the user's email (`ki/` is never forwarded from the browser)."""
    if _token_ok(request):
        return request.headers.get("x-vilikon-benutzer") or "cockpit"
    user = request.headers.get("x-vilikon-benutzer")
    if not user:
        raise Refusal(401, t("error.login"))
    return user


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": VERSION}


# --- vilikon.modul/1 -------------------------------------------------------------------------------------------------


@app.get("/ki/modul")
def module(_: str = Depends(cockpit)) -> dict:
    return describe()


@app.get("/ki/anleitung", response_class=PlainTextResponse)
def instruction(_: str = Depends(cockpit)) -> str:
    return t("instruction")


@app.get("/ki/protokoll")
def protocol(seit: str = "", bis: str = "9", _: str = Depends(cockpit)) -> list[dict]:
    return [{"zeit": r["time"], "wer": r["who"], "was": r["what"]} for r in get_store().log_between(seit, bis)]


@app.get("/ki/ereignisse")
def events(seit: str = "", _: str = Depends(cockpit)) -> dict:
    rows = get_store().events_for_cockpit(seit, MAX_EVENTS)
    return {
        "ereignisse": [
            {
                "id": r["id"],
                "art": r["kind"],
                "titel": r["title"],
                "text": r["text"],
                "time": r["time"],
                "data": json.loads(r["data"]),
            }
            for r in rows
        ]
    }


def _row(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "kind": doc["kind"],
        "sender": doc["sender"],
        "subject": doc["subject"],
        "date": doc["date"] or doc["received_at"][:10],
        "file_number": doc["file_number"],
        "action": doc["action"],
        "amount": doc["amount"],
        "status": doc["status"],
        "reason": t(f"reason.{doc['reason']}") if doc["reason"] else "",
        "confidential": bool(doc["confidential"]),
        "case_id": doc["case_id"],
    }


def _search(query: str, kind: str, since: str, until: str, confidential: bool) -> dict:
    found = get_store().search(query, kind=kind, since=since, until=until, confidential=confidential)
    return {"documents": [_row(d) for d in found]}


def _full(doc_id: str, confidential: bool) -> dict:
    store = get_store()
    doc = store.document(doc_id)
    if not doc or (doc["confidential"] and not confidential):
        raise Refusal(404, t("error.no_document"))
    case = [_row(d) for d in store.case_documents(doc["case_id"]) if d["id"] != doc_id] if doc["case_id"] else []
    if not confidential:
        case = [c for c in case if not c["confidential"]]
    return _row(doc) | {
        "text": doc["text"],
        "due_dates": store.due_dates(doc_id),
        "iban": doc["iban"],
        "payment_reference": doc["payment_reference"],
        "case": case,
    }


@app.get("/ki/documents")
def search_documents(
    query: str = "",
    kind: str = "",
    since: str = Query("", alias="from"),
    until: str = Query("", alias="to"),
    _: str = Depends(cockpit),
) -> dict:
    return _search(query, kind, since, until, False)


@app.get("/ki/documents/{doc_id}")
def read_document(doc_id: str, _: str = Depends(cockpit)) -> dict:
    return _full(doc_id, False)


@app.get("/ki/confidential/documents")
def search_confidential(
    query: str = "",
    kind: str = "",
    since: str = Query("", alias="from"),
    until: str = Query("", alias="to"),
    _: str = Depends(cockpit),
) -> dict:
    return _search(query, kind, since, until, True)


@app.get("/ki/confidential/documents/{doc_id}")
def read_confidential(doc_id: str, _: str = Depends(cockpit)) -> dict:
    return _full(doc_id, True)


@app.get("/ki/due_dates")
def due_dates(
    since: str = Query("", alias="from"), until: str = Query("", alias="to"), _: str = Depends(cockpit)
) -> dict:
    """Every due date between from and to (default: today and the next 10 days). Confidential letters show only kind
    and date, so the Office Manager can name them in the morning briefing without reading them."""
    start = since or date.today().isoformat()
    end = until or (date.fromisoformat(start) + timedelta(days=10)).isoformat()
    out = []
    for d in get_store().due_dates_between(start, end):
        hidden = bool(d["confidential"])
        out.append(
            {
                "date": d["date"],
                "kind": d["kind"],
                "amount": None if hidden else d["amount"],
                "text": t("due.confidential") if hidden else d["text"],
                "document_id": d["document_id"],
                "sender": t("due.confidential") if hidden else d["sender"],
                "subject": "" if hidden else d["subject"],
                "confidential": hidden,
            }
        )
    return {"due_dates": out}


def _receipt(doc_id: str) -> dict:
    doc = get_store().document(doc_id)
    if not doc or not doc["is_receipt"]:
        raise Refusal(404, t("error.no_receipt"))
    return doc


@app.get("/ki/receipts/{doc_id}")
def receipt_data(doc_id: str, _: str = Depends(cockpit)) -> dict:
    doc = _receipt(doc_id)
    return {
        "id": doc["id"],
        "sender": doc["sender"],
        "date": doc["date"],
        "number": doc["file_number"],
        "amount": doc["amount"],
        "iban": doc["iban"],
        "payment_reference": doc["payment_reference"],
        "subject": doc["subject"],
        "file_name": doc["name"],
        "file": f"ki/receipts/{doc_id}/file",
    }


@app.get("/ki/receipts/{doc_id}/file")
def receipt_file(doc_id: str, _: str = Depends(cockpit)) -> Response:
    doc = _receipt(doc_id)
    media = "application/pdf" if doc["suffix"] == ".pdf" else "application/octet-stream"
    return Response(get_store().original(doc), media_type=media)


@app.get("/ki/karten/mail")
def card_mail(_: str = Depends(cockpit)) -> dict:
    store = get_store()
    review = store.documents(status=("review",))
    soon = store.due_dates_between(date.today().isoformat(), (date.today() + timedelta(days=10)).isoformat())
    lines = [{"text": pipeline.title(d)[:80], "wert": t("card.review")} for d in review[:4]]
    for d in soon[: 8 - len(lines)]:
        name = t("due.confidential") if d["confidential"] else (d["sender"] or d["subject"])
        lines.append({"text": f"{name[:60]}: {t('due.' + d['kind'])}", "wert": d["date"]})
    tone = "kritisch" if review else ("warn" if soon else "gut")
    return {"zahl": str(len(review) + len(soon)), "text": t("card.mail_text"), "ton": tone, "zeilen": lines}


@app.get("/ki/karten/pages")
def card_pages(_: str = Depends(cockpit)) -> dict:
    s = budget.state(get_store())
    lines = [{"text": t("card.this_month"), "wert": f"{s['pages']} / {s['cap'] or '∞'}"}]
    if s["waiting"]:
        lines.append({"text": t("card.waiting"), "wert": str(s["waiting"])})
    return {
        "zahl": str(s["pages"]),
        "text": t("card.pages_text"),
        "ton": "warn" if s["waiting"] else "neutral",
        "zeilen": lines,
    }


@app.get("/ki/pages")
def pages(_: str = Depends(cockpit)) -> dict:
    """For the operator's weekly pulse: what the free offer costs."""
    return budget.state(get_store())


# --- sources ---------------------------------------------------------------------------------------------------------

SECRET_KEYS = ("password", "key", "token", "json")


def _public(source: dict) -> dict:
    out = {k: v for k, v in source.items() if not k.startswith("_") and not any(s in k for s in SECRET_KEYS)}
    return out | {"error": source.get("_error") or "", "last_fetch": source.get("_last_fetch")}


@app.put("/ki/sources")
async def set_sources(request: Request, who: str = Depends(cockpit)) -> dict:
    """The cockpit pushes all sources at once (settings plus credentials from the vault); missing ones are removed.
    `mistral_key`: the customer's own key (lifts the page cap); "" removes it, absent leaves it."""
    try:
        body = await request.json()
    except ValueError as e:
        raise Refusal(400, t("error.json")) from e
    sources = body.get("sources") if isinstance(body, dict) else None
    if not isinstance(sources, list):
        raise Refusal(400, t("error.sources_list"))
    for s in sources:
        if not isinstance(s, dict) or not _SOURCE_ID.match(str(s.get("id") or "")):
            raise Refusal(400, t("error.source_id"))
        if s.get("kind") not in intake.KINDS:
            raise Refusal(400, t("intake.unknown_kind", kind=s.get("kind") or "?"))
    store = get_store()
    store.set_sources(sources)
    if isinstance(body.get(budget.OWN_KEY), str):
        store.set_value(budget.OWN_KEY, body[budget.OWN_KEY].strip())
    store.log(who, t("log.sources", n=len(sources)))
    return {"sources": [_public(s) for s in store.sources()], "pages": budget.state(store)}


@app.get("/ki/sources")
def sources(_: str = Depends(cockpit)) -> dict:
    store = get_store()
    return {"sources": [_public(s) for s in store.sources()], "pages": budget.state(store)}


@app.post("/ki/sync")
def sync_now(_: str = Depends(cockpit)) -> dict:
    """Fetch from the sources now (after `PUT ki/sources`, to check them)."""
    store = get_store()
    counts = pipeline.intake_pass(store)
    return counts | {"sources": [_public(s) for s in store.sources()]}


# --- vilikon.wissen/1 ------------------------------------------------------------------------------------------------


def _file_name(doc: dict) -> str:
    day = doc["date"] or doc["received_at"][:10]
    words = re.sub(r"[\\/:*?\"<>|]+", " ", pipeline.title(doc)).strip()[:80]
    return f"{day} {words}.md"


def _markdown(doc: dict, due_dates: list[dict]) -> str:
    amount = f"{doc['amount']:.2f} EUR" if doc["amount"] is not None else ""
    rows = [
        ("kind", t(f"kind.{doc['kind']}")),
        ("sender", doc["sender"]),
        ("date", doc["date"]),
        ("file_number", doc["file_number"]),
        ("action", t(f"action.{doc['action']}") if doc["action"] else ""),
        ("amount", amount),
    ]
    head = [f"# {pipeline.title(doc)}", ""] + [f"- {t(f'field.{k}')}: {v}" for k, v in rows if v]
    head += [f"- {t('field.due_date')}: {d['date']} ({t('due.' + d['kind'])})" for d in due_dates]
    return "\n".join([*head, "", "---", "", doc["text"]]) + "\n"


@app.get("/ki/wissen/dateien")
def knowledge_files(_: str = Depends(cockpit)) -> dict:
    """The whole list each time. Each letter as Markdown of its recognised text, so the cockpit does not run OCR a
    second time. Besides the standard's fields, per file `sensibel` (confidential letters) and `meta`."""
    store = get_store()
    out = []
    for doc in store.documents(status=FILED):
        if not doc["text"].strip():
            continue
        name, due = _file_name(doc), store.due_dates(doc["id"])
        year = (doc["date"] or doc["received_at"])[:4]
        out.append(
            {
                "id": doc["id"],
                "name": name,
                "pfad": f"{t('knowledge.folder')}/{year}/{name}",
                "version": f"{doc['sha256'][:12]}-{doc['updated_at']}",
                "groesse": len(_markdown(doc, due).encode()),
                "sensibel": bool(doc["confidential"]),
                "meta": {
                    "kind": doc["kind"],
                    "sender": doc["sender"],
                    "date": doc["date"],
                    "file_number": doc["file_number"],
                    "action": doc["action"],
                    "due_dates": [d["date"] for d in due],
                    "status": doc["status"],
                },
            }
        )
    return {"dateien": out}


@app.get("/ki/wissen/datei")
def knowledge_file(id: str, _: str = Depends(cockpit)) -> PlainTextResponse:
    store = get_store()
    doc = store.document(id)
    if not doc or doc["status"] not in FILED:
        raise Refusal(404, t("error.no_document"))
    return PlainTextResponse(_markdown(doc, store.due_dates(id)), media_type="text/markdown; charset=utf-8")


# --- page and phone --------------------------------------------------------------------------------------------------

OWNER_ROLE = "kunde"  # the core's role of the owner; the operator (`betreiber`) sees no confidential letters
PAGE_KEYS = (
    "module.name",
    "page.upload",
    "page.send",
    "page.review",
    "page.inbox",
    "page.empty",
    "page.confidential",
    "page.pages",
    "page.reading",
)


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), who: str = Depends(person)) -> dict:
    """The pages of one letter, photographed on the phone (or one PDF shared into Vilikon)."""
    got_files = [(f.filename or "photo.jpg", await f.read()) for f in files]
    try:
        name, data = to_pdf(got_files)
    except UploadError as e:
        raise Refusal(400, str(e)) from e
    store = get_store()
    got = await run_in_threadpool(pipeline.receive, store, name, data, "phone", who)
    doc = got.document if got.duplicate else await run_in_threadpool(pipeline.process, store, got.document)
    text = t("upload.duplicate") if got.duplicate else t(f"upload.status_{doc['status']}")
    return {"id": doc["id"], "duplicate": got.duplicate, "status": doc["status"], "text": text}


@app.get("/api/documents")
def page_documents(request: Request, who: str = Depends(person)) -> dict:
    """What the page shows: the latest 50 letters and the review list; confidential ones only for the owner."""
    owner = request.headers.get("x-vilikon-rolle") == OWNER_ROLE
    store = get_store()
    docs = [d for d in reversed(store.documents()) if owner or not d["confidential"]]
    rows = [
        _row(d) | {"title": pipeline.title(d), "kind_text": t(f"kind.{d['kind']}") if d["kind"] else ""} for d in docs
    ]
    return {
        "review": [r for r in rows if r["status"] == "review"],
        "documents": rows[:50],
        "pages": budget.state(store),
    }


PAGE = """<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:720px;padding:16px;
color:#1f2328;background:#fff}}@media(prefers-color-scheme:dark){{body{{color:#e6edf3;background:#0d1117}}}}
li{{margin:6px 0}}small{{opacity:.7}}button{{font-size:1rem;padding:8px 14px}}</style>
<h1>{title}</h1><form id="f"><label>{upload}<br><input type="file" name="files" accept="image/*,application/pdf"
capture="environment" multiple required></label> <button>{send}</button><p id="m" role="status"></p></form>
<h2>{review}</h2><ul id="p"></ul><h2>{inbox}</h2><ul id="d"></ul><p><small id="s"></small></p>
<script>const T={texts};
function li(r){{const e=document.createElement("li");e.textContent=r.date+" · "+(r.kind_text?r.kind_text+" · ":"")+r.title+
(r.confidential?" ("+T["page.confidential"]+")":"")+(r.reason?" – "+r.reason:"");return e}}
function fill(id,rows){{const u=document.getElementById(id);u.replaceChildren(...rows.map(li));
if(!rows.length){{const e=document.createElement("li");e.textContent=T["page.empty"];u.append(e)}}}}
function load(){{fetch("api/documents").then(r=>r.json()).then(d=>{{fill("p",d.review);fill("d",d.documents);
document.getElementById("s").textContent=T["page.pages"]+": "+d.pages.pages+" / "+(d.pages.cap||"∞")}})}}
document.getElementById("f").onsubmit=e=>{{e.preventDefault();const m=document.getElementById("m");m.textContent=T["page.reading"];
fetch("api/upload",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(d=>{{m.textContent=d.text||d.fehler;
e.target.reset();load()}})}};load()</script></html>"""


@app.get("/", response_class=HTMLResponse)
def page(_: str = Depends(person)) -> str:
    """Inbox, the review list and the phone upload. Relative links: the page lives under /modul/dms/."""
    texts = json.dumps({k: t(k) for k in PAGE_KEYS}, ensure_ascii=False).replace("<", "\\u003c")
    esc = {k: html.escape(t(f"page.{k}")) for k in ("upload", "send", "review", "inbox")}
    return PAGE.format(lang=config.settings.language, title=html.escape(t("module.name")), texts=texts, **esc)
