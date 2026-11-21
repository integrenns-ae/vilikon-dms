"""The DMS service. Only the cockpit calls `ki/…`, with the tool's token (vilikon.modul/1, vilikon.wissen/1). People
reach `/` and `/api/…` through the core at /werkzeug/<slug>/, behind the cockpit's login. The DMS never calls the
cockpit.

Every request but `/health` carries the token: as a Werkzeug `X-Vilikon-Token` (the Verwalter's `VILIKON_TOKEN`),
standalone `Authorization: Bearer $DMS_TOKEN`. Without either configured, everything is refused.

What the DMS brings to the cockpit (rights, functions, events, cards) the core reads from MODULE.json and BRIEFING.md in
the released repository (app/module.py). Keys and paths the core's standards define stay as they are there
(`ki/ereignisse`, `ki/wissen/…`, `{"fehler": …}`, the card fields); everything else is the DMS's own and English."""

from __future__ import annotations

import asyncio
import hmac
import html
import json
import logging
import os
import re
import shutil
import tempfile
import threading
from contextlib import asynccontextmanager, contextmanager
from datetime import date, timedelta
from typing import BinaryIO

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException

from app import VERSION, budget, config, pipeline
from app import upload as upload_rules
from app.store import Store
from app.texts import t
from app.upload import UploadError, to_pdf

log = logging.getLogger(__name__)

MAX_EVENTS = 5  # the cockpit takes at most this many per fetch
MAX_CARD_LINES = 8
FILED = ("done", "review")
FIRST_PASS_S = 5.0  # after a start: the owner who just released the scanner sees its letters soon
CHECK_TIMEOUT_S = 10
UPLOAD_LIMIT = upload_rules.MAX_TOTAL + 1024 * 1024  # the photos and the form around them
_store: Store | None = None
_store_lock = threading.Lock()


def get_store() -> Store:
    global _store
    with _store_lock:
        if _store is None or _store.data_dir != config.settings.data_dir:
            _store = Store(config.settings.data_dir)
        return _store


class Refusal(Exception):
    def __init__(self, status: int, text: str) -> None:
        self.status, self.text = status, text


# One pass over the file stores at a time, whether the loop or `POST ki/sync` starts it.
pass_lock = threading.Lock()


def _pass() -> None:
    """The caller holds `pass_lock`."""
    try:
        pipeline.intake_pass(get_store())
    except Exception:
        log.exception("intake pass failed")


def _loop(stop: threading.Event) -> None:
    wait = FIRST_PASS_S
    while not stop.wait(wait):
        with pass_lock:
            _pass()
        wait = max(1, config.settings.intake_interval_min) * 60


def start_pass() -> bool:
    """A pass in a thread of its own; False when one is running already."""
    if not pass_lock.acquire(blocking=False):
        return False

    def run() -> None:
        try:
            _pass()
        finally:
            pass_lock.release()

    threading.Thread(target=run, daemon=True, name="sync").start()
    return True


@contextmanager
def _own_tmp():
    """Temporary files (the spooled uploads above all) go below DATA_DIR, not into the /tmp all tools share."""
    tmp = config.settings.data_dir.resolve() / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)  # what a crash left
    tmp.mkdir(mode=0o700, parents=True)
    before = os.environ.get("TMPDIR"), tempfile.tempdir
    os.environ["TMPDIR"] = tempfile.tempdir = str(tmp)
    try:
        yield
    finally:
        if before[0] is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = before[0]
        tempfile.tempdir = before[1]


@asynccontextmanager
async def lifespan(app: FastAPI):
    stop = threading.Event()
    with _own_tmp():
        if config.settings.intake_interval_min > 0:
            threading.Thread(target=_loop, args=(stop,), daemon=True, name="intake").start()
        try:
            yield
        finally:
            stop.set()


app = FastAPI(title="vilikon-dms", version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def _upload_size(request: Request, call_next):
    """A letter that is too big is refused before its body is spooled; to_pdf counts again for bodies without a
    length."""
    if request.url.path == "/api/upload":
        try:
            length = int(request.headers.get("content-length") or 0)
        except ValueError:
            length = 0
        if length > UPLOAD_LIMIT:
            text = t("upload.too_big_total", mb=upload_rules.MAX_TOTAL // (1024 * 1024))
            return JSONResponse({"fehler": text}, status_code=413)
    return await call_next(request)


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


def _same(given: str, wanted: str) -> bool:
    return bool(wanted) and hmac.compare_digest(given.encode(), wanted.encode())


def _token_ok(request: Request) -> bool:
    s = config.settings
    return _same(request.headers.get("x-vilikon-token", ""), s.vilikon_token) or _same(
        request.headers.get("authorization", ""), f"Bearer {s.token}" if s.token else ""
    )


def cockpit(request: Request) -> str:
    """Every ki/ call: the token, or nothing. Returns who asks (the employee, or `cockpit`)."""
    if not _token_ok(request):
        raise Refusal(401, t("error.token"))
    return request.headers.get("x-vilikon-mitarbeiter") or "cockpit"


def person(request: Request) -> str:
    """The page and the phone upload, reached through the core's /werkzeug/<slug>/: it has checked the login and sends
    the token with the user's email (`X-Vilikon-Benutzer`), role and `X-Vilikon-Owner`. A user header without the
    token counts for nothing. (`ki/` is never forwarded from the browser.)"""
    user = request.headers.get("x-vilikon-benutzer", "").strip()
    if not _token_ok(request) or not user:
        raise Refusal(401, t("error.login"))
    return user


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": VERSION}


# --- vilikon.modul/1 -------------------------------------------------------------------------------------------------


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
    """Pages this month, waiting letters, and one line per file store that failed last time (stored, no live check:
    the core waits 5 s for a card)."""
    store = get_store()
    s = budget.state(store)
    lines = [{"text": t("card.this_month"), "wert": f"{s['pages']} / {s['cap'] or '∞'}"}]
    if s["waiting"]:
        lines.append({"text": t("card.waiting"), "wert": str(s["waiting"])})
    failing = [x for x in pipeline.source_list(store) if x["error"]]
    for x in failing[: MAX_CARD_LINES - len(lines)]:
        lines.append({"text": f"{x['id']}: {x['error']}"[:120], "wert": t("card.source_error")})
    return {
        "zahl": str(s["pages"]),
        "text": t("card.pages_text"),
        "ton": "kritisch" if failing else ("warn" if s["waiting"] else "neutral"),
        "zeilen": lines,
    }


@app.get("/ki/pages")
def pages(_: str = Depends(cockpit)) -> dict:
    """For the operator's weekly pulse: what the free offer costs."""
    return budget.state(get_store())


# --- file stores ----------------------------------------------------------------------------------------------------


@app.post("/ki/sync", status_code=202)
def sync_now(_: str = Depends(cockpit)) -> dict:
    """Fetch from the file stores now, in the background: the core's call gives up after 60 s, a pass can take longer.
    `ki/pruefen` shows afterwards what came of it."""
    started = start_pass()
    return {"status": "started" if started else "running", "text": t("sync.started" if started else "sync.running")}


async def _check(store: Store, source: dict) -> str:
    try:
        return await asyncio.wait_for(asyncio.to_thread(pipeline.check_source, store, source), CHECK_TIMEOUT_S)
    except TimeoutError:
        error = t("check.timeout", seconds=CHECK_TIMEOUT_S)
        store.source_state(source["id"], error, fetched=False)
        return error


def _check_text(rows: list[dict], ocr: dict) -> str:
    if ocr["ok"]:
        key = t("check.ocr_operator", used=ocr["pages_used"], cap=ocr["cap"] or "∞") if ocr["operator"] else ""
        parts = [key or t("check.ocr_own", used=ocr["pages_used"])]
    elif budget.wrong_service():
        parts = [t("check.wrong_service", service=config.settings.ocr_service)]
    else:
        parts = [t("check.no_key")]
    failing = [r for r in rows if not r["ok"]]
    if not rows:
        parts.append(t("check.no_sources"))
    elif not failing:
        parts.append(t("check.sources_ok", n=len(rows)))
    parts += [t("check.source_failed", id=r["id"], error=r["error"]) for r in failing]
    return " ".join(parts)


@app.get("/ki/pruefen")
async def check(_: str = Depends(cockpit)) -> dict:
    """For the IT Specialist after setting it up: does every file store answer (a quick look into its folder, at most
    10 s each, all at once), is there an OCR key, how many pages are left."""
    store = get_store()
    sources = pipeline.sources()
    errors = await asyncio.gather(*(_check(store, x) for x in sources))
    fetched = {x["id"]: x["last_fetch"] for x in pipeline.source_list(store)}
    rows = [
        {
            "id": x["id"],
            "protocol": x["protocol"],
            "host": x["host"],
            "ok": not error,
            "error": error,
            "last_fetch": fetched.get(x["id"]),
        }
        for x, error in zip(sources, errors, strict=True)
    ]
    pages = budget.state(store)
    ocr = {
        "ok": bool(budget.api_key()),
        "operator": budget.operator(),
        "pages_used": pages["pages"],
        "cap": pages["cap"],
    }
    return {
        "ok": ocr["ok"] and all(r["ok"] for r in rows),
        "text": _check_text(rows, ocr),
        "sources": rows,
        "ocr": ocr,
    }


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
    "page.sources",
    "page.fetch",
    "page.trust",
    "page.never_fetched",
)


def is_owner(request: Request) -> bool:
    """The core says who the owner is; a role name says nothing (the owner who set Vilikon up has the role
    `betreiber`). Only the owner sees confidential letters and the file stores."""
    return request.headers.get("x-vilikon-owner", "").strip() == "1"


def owner(request: Request, who: str = Depends(person)) -> str:
    if not is_owner(request):
        raise Refusal(403, t("error.not_owner"))
    return who


def _assemble(files: list[tuple[str, BinaryIO]]) -> tuple[str, bytes]:
    with pipeline.HEAVY:
        return to_pdf(files)


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), who: str = Depends(person)) -> dict:
    """The pages of one letter, photographed on the phone (or one PDF shared into Vilikon). The photos stay in their
    spool files (below DATA_DIR) until to_pdf reads them, one at a time."""
    got_files = [(f.filename or "photo.jpg", f.file) for f in files]
    try:
        name, data = await asyncio.to_thread(_assemble, got_files)
    except UploadError as e:
        raise Refusal(400, str(e)) from e
    store = get_store()
    got = await asyncio.to_thread(pipeline.receive, store, name, data, "phone", who)
    doc = got.document if got.duplicate else await asyncio.to_thread(pipeline.process, store, got.document)
    text = t("upload.duplicate") if got.duplicate else t(f"upload.status_{doc['status']}")
    return {"id": doc["id"], "duplicate": got.duplicate, "status": doc["status"], "text": text}


@app.get("/api/documents")
def page_documents(request: Request, who: str = Depends(person)) -> dict:
    """What the page shows: the latest 50 letters and the review list; confidential ones and the file stores only for
    the owner."""
    is_it = is_owner(request)
    store = get_store()
    docs = [d for d in reversed(store.documents()) if is_it or not d["confidential"]]
    rows = [
        _row(d) | {"title": pipeline.title(d), "kind_text": t(f"kind.{d['kind']}") if d["kind"] else ""} for d in docs
    ]
    return {
        "review": [r for r in rows if r["status"] == "review"],
        "documents": rows[:50],
        "pages": budget.state(store),
        "owner": is_it,
        "sources": pipeline.source_list(store) if is_it else [],
    }


@app.post("/api/sync")
def page_sync(who: str = Depends(owner)) -> dict:
    """The owner's "Fetch now"."""
    return {"text": t("sync.started" if start_pass() else "sync.running")}


@app.post("/api/sources/{source_id}/trust")
def trust_host_key(source_id: str, who: str = Depends(owner)) -> dict:
    """The owner accepts the new key an SFTP server showed (it was set up anew); then it is fetched again."""
    store = get_store()
    if source_id not in {x["id"] for x in pipeline.sources()} or not store.accept_host_key(source_id):
        raise Refusal(404, t("error.no_new_host_key"))
    store.log(who, t("log.host_key_accepted", source=source_id))
    start_pass()
    return {"text": t("page.trusted")}


PAGE = """<!doctype html><html lang="{lang}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>body{{font-family:system-ui,sans-serif;margin:0 auto;max-width:720px;padding:16px;
color:#1f2328;background:#fff}}@media(prefers-color-scheme:dark){{body{{color:#e6edf3;background:#0d1117}}}}
li{{margin:6px 0}}small{{opacity:.7}}button{{font-size:1rem;padding:8px 14px}}</style>
<h1>{title}</h1><form id="f"><label>{upload}<br><input type="file" name="files" accept="image/*,application/pdf"
capture="environment" multiple required></label> <button>{send}</button><p id="m" role="status"></p></form>
<h2>{review}</h2><ul id="p"></ul><h2>{inbox}</h2><ul id="d"></ul><p><small id="s"></small></p>
<section id="o" hidden><h2>{sources}</h2><ul id="q"></ul><button id="g" type="button">{fetch}</button>
<p id="r" role="status"></p></section>
<script>const T={texts};
function li(r){{const e=document.createElement("li");e.textContent=r.date+" · "+(r.kind_text?r.kind_text+" · ":"")+r.title+
(r.confidential?" ("+T["page.confidential"]+")":"")+(r.reason?" – "+r.reason:"");return e}}
function fill(id,rows){{const u=document.getElementById(id);u.replaceChildren(...rows.map(li));
if(!rows.length){{const e=document.createElement("li");e.textContent=T["page.empty"];u.append(e)}}}}
function say(d){{document.getElementById("r").textContent=d.text||d.fehler}}
function post(path){{fetch(path,{{method:"POST"}}).then(r=>r.json()).then(d=>{{say(d);setTimeout(load,3000)}})}}
function source(x){{const e=document.createElement("li");e.textContent=x.id+" ("+x.protocol+" "+x.host+"): "+
(x.error||(x.last_fetch?x.last_fetch.slice(0,16).replace("T"," "):T["page.never_fetched"]));if(x.host_key_new){{
const b=document.createElement("button");b.type="button";b.textContent=T["page.trust"];b.title=x.host_key_new;
b.onclick=()=>post("api/sources/"+encodeURIComponent(x.id)+"/trust");e.append(" ",b)}}return e}}
function load(){{fetch("api/documents").then(r=>r.json()).then(d=>{{fill("p",d.review);fill("d",d.documents);
document.getElementById("s").textContent=T["page.pages"]+": "+d.pages.pages+" / "+(d.pages.cap||"∞");
document.getElementById("o").hidden=!d.owner;document.getElementById("q").replaceChildren(...d.sources.map(source))}})}}
document.getElementById("g").onclick=()=>post("api/sync");
document.getElementById("f").onsubmit=e=>{{e.preventDefault();const m=document.getElementById("m");m.textContent=T["page.reading"];
fetch("api/upload",{{method:"POST",body:new FormData(e.target)}}).then(r=>r.json()).then(d=>{{m.textContent=d.text||d.fehler;
e.target.reset();load()}})}};load()</script></html>"""


@app.get("/", response_class=HTMLResponse)
def page(_: str = Depends(person)) -> str:
    """Inbox, the review list and the phone upload; for the owner also the file stores and "Fetch now". Relative links:
    the page lives under the core's prefix."""
    texts = json.dumps({k: t(k) for k in PAGE_KEYS}, ensure_ascii=False).replace("<", "\\u003c")
    esc = {k: html.escape(t(f"page.{k}")) for k in ("upload", "send", "review", "inbox", "sources", "fetch")}
    return PAGE.format(lang=config.settings.language, title=html.escape(t("module.name")), texts=texts, **esc)
