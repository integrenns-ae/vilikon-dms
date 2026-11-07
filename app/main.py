"""The DMS service. Only the cockpit calls it: `ki/…` with the service token (vilikon.modul/1, vilikon.wissen/1), and
`api/upload` from the phone through Caddy's forward_auth. The DMS never calls the cockpit."""

from __future__ import annotations

import hmac
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from starlette.exceptions import HTTPException

from app import VERSION, budget, config, intake, pipeline
from app.modul import describe
from app.store import Store
from app.texte import t
from app.upload import UploadError, to_pdf

log = logging.getLogger(__name__)

MAX_EVENTS = 5  # the cockpit takes at most this many per fetch
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
    return JSONResponse(
        {"fehler": t("fehler.pfad") if e.status_code in (404, 405) else str(e.detail)}, status_code=e.status_code
    )


@app.exception_handler(RequestValidationError)
async def _invalid(request: Request, e: RequestValidationError) -> JSONResponse:
    where = ", ".join(".".join(str(x) for x in err.get("loc", ())[1:]) for err in e.errors()[:3])
    return JSONResponse({"fehler": t("fehler.eingabe", fehler=where)}, status_code=400)


def _token_ok(request: Request) -> bool:
    token = config.settings.token
    given = request.headers.get("authorization", "")
    return bool(token) and hmac.compare_digest(given.encode(), f"Bearer {token}".encode())


def cockpit(request: Request) -> str:
    """Every ki/ call: the service token, or nothing. Returns who asks (the employee, or `cockpit`)."""
    if not _token_ok(request):
        raise Refusal(401, t("fehler.token"))
    return request.headers.get("x-vilikon-mitarbeiter") or "cockpit"


def person(request: Request) -> str:
    """The phone upload: Caddy's forward_auth has checked the login and set the user; the cockpit may use the token."""
    if _token_ok(request):
        return request.headers.get("x-vilikon-benutzer") or "cockpit"
    user = request.headers.get("x-vilikon-benutzer")
    if not user:
        raise Refusal(401, t("fehler.anmeldung"))
    return user


@app.get("/gesund")
def health() -> dict:
    return {"ok": True, "version": VERSION}


# --- vilikon.modul/1 -------------------------------------------------------------------------------------------------


@app.get("/ki/modul")
def modul(_: str = Depends(cockpit)) -> dict:
    return describe()


@app.get("/ki/anleitung", response_class=PlainTextResponse)
def instruction(_: str = Depends(cockpit)) -> str:
    return t("anleitung")


@app.get("/ki/protokoll")
def protocol(seit: str = "", bis: str = "9", _: str = Depends(cockpit)) -> list[dict]:
    return get_store().log_between(seit, bis)


@app.get("/ki/ereignisse")
def events(seit: str = "", _: str = Depends(cockpit)) -> dict:
    rows = get_store().events_for_cockpit(seit, MAX_EVENTS)
    return {
        "ereignisse": [
            {
                "id": r["id"],
                "art": r["art"],
                "titel": r["titel"],
                "text": r["text"],
                "zeit": r["zeit"],
                "daten": json.loads(r["daten"]),
            }
            for r in rows
        ]
    }


def _row(doc: dict) -> dict:
    return {
        "id": doc["id"],
        "art": doc["art"],
        "absender": doc["absender"],
        "betreff": doc["betreff"],
        "datum": doc["datum"] or doc["empfangen"][:10],
        "aktenzeichen": doc["aktenzeichen"],
        "handlung": doc["handlung"],
        "betrag": doc["betrag"],
        "status": doc["status"],
        "grund": t(f"grund.{doc['grund']}") if doc["grund"] else "",
        "vertraulich": bool(doc["vertraulich"]),
        "fall_id": doc["fall_id"],
    }


def _search(suche: str, art: str, von: str, bis: str, confidential: bool) -> dict:
    found = get_store().search(suche, kind=art, since=von, until=bis, confidential=confidential)
    return {"dokumente": [_row(d) for d in found]}


def _full(doc_id: str, confidential: bool) -> dict:
    store = get_store()
    doc = store.document(doc_id)
    if not doc or (doc["vertraulich"] and not confidential):
        raise Refusal(404, t("fehler.dokument_fehlt"))
    case = [_row(d) for d in store.case_documents(doc["fall_id"]) if d["id"] != doc_id] if doc["fall_id"] else []
    if not confidential:
        case = [c for c in case if not c["vertraulich"]]
    return _row(doc) | {
        "text": doc["text"],
        "fristen": store.deadlines(doc_id),
        "iban": doc["iban"],
        "verwendungszweck": doc["verwendungszweck"],
        "fall": case,
    }


@app.get("/ki/dokumente")
def search(suche: str = "", art: str = "", von: str = "", bis: str = "", _: str = Depends(cockpit)) -> dict:
    return _search(suche, art, von, bis, False)


@app.get("/ki/dokumente/{doc_id}")
def document(doc_id: str, _: str = Depends(cockpit)) -> dict:
    return _full(doc_id, False)


@app.get("/ki/vertraulich/dokumente")
def search_confidential(
    suche: str = "", art: str = "", von: str = "", bis: str = "", _: str = Depends(cockpit)
) -> dict:
    return _search(suche, art, von, bis, True)


@app.get("/ki/vertraulich/dokumente/{doc_id}")
def document_confidential(doc_id: str, _: str = Depends(cockpit)) -> dict:
    return _full(doc_id, True)


@app.get("/ki/fristen")
def deadlines(von: str = "", bis: str = "", _: str = Depends(cockpit)) -> dict:
    """Every due date between von and bis (default: today and the next 10 days). Confidential letters show only kind
    and date, so the Office Manager can name them in the morning briefing without reading them."""
    start = von or date.today().isoformat()
    end = bis or (date.fromisoformat(start) + timedelta(days=10)).isoformat()
    out = []
    for f in get_store().deadlines_between(start, end):
        hidden = bool(f["vertraulich"])
        out.append(
            {
                "datum": f["datum"],
                "art": f["art"],
                "betrag": None if hidden else f["betrag"],
                "text": t("frist.vertraulich") if hidden else f["text"],
                "dokument_id": f["dokument_id"],
                "absender": t("frist.vertraulich") if hidden else f["absender"],
                "betreff": "" if hidden else f["betreff"],
                "vertraulich": hidden,
            }
        )
    return {"fristen": out}


@app.get("/ki/belege/{doc_id}")
def receipt(doc_id: str, _: str = Depends(cockpit)) -> dict:
    store = get_store()
    doc = store.document(doc_id)
    if not doc or not doc["ist_beleg"]:
        raise Refusal(404, t("fehler.beleg_fehlt"))
    return {
        "id": doc["id"],
        "absender": doc["absender"],
        "datum": doc["datum"],
        "nummer": doc["aktenzeichen"],
        "betrag": doc["betrag"],
        "iban": doc["iban"],
        "verwendungszweck": doc["verwendungszweck"],
        "betreff": doc["betreff"],
        "dateiname": doc["name"],
        "datei": f"ki/belege/{doc_id}/datei",
    }


@app.get("/ki/belege/{doc_id}/datei")
def receipt_file(doc_id: str, _: str = Depends(cockpit)):
    store = get_store()
    doc = store.document(doc_id)
    if not doc or not doc["ist_beleg"]:
        raise Refusal(404, t("fehler.beleg_fehlt"))
    media = "application/pdf" if doc["endung"] == ".pdf" else "application/octet-stream"
    return Response(store.original(doc), media_type=media)


@app.get("/ki/karten/post")
def card_post(_: str = Depends(cockpit)) -> dict:
    store = get_store()
    check = store.documents(status=("pruefen",))
    soon = store.deadlines_between(date.today().isoformat(), (date.today() + timedelta(days=10)).isoformat())
    lines = [{"text": pipeline.title(d)[:80], "wert": t("karte.pruefen")} for d in check[:4]]
    for f in soon[: 8 - len(lines)]:
        name = t("frist.vertraulich") if f["vertraulich"] else (f["absender"] or f["betreff"])
        lines.append({"text": f"{name[:60]}: {t('frist.' + f['art'])}", "wert": f["datum"]})
    tone = "kritisch" if check else ("warn" if soon else "gut")
    return {"zahl": str(len(check) + len(soon)), "text": t("karte.post_text"), "ton": tone, "zeilen": lines}


@app.get("/ki/karten/seiten")
def card_pages(_: str = Depends(cockpit)) -> dict:
    s = budget.state(get_store())
    lines = [{"text": t("karte.seiten_monat"), "wert": f"{s['seiten']} / {s['grenze'] or '∞'}"}]
    if s["wartend"]:
        lines.append({"text": t("karte.wartend"), "wert": str(s["wartend"])})
    tone = "warn" if s["wartend"] else "neutral"
    return {"zahl": str(s["seiten"]), "text": t("karte.seiten_text"), "ton": tone, "zeilen": lines}


@app.get("/ki/seiten")
def pages(_: str = Depends(cockpit)) -> dict:
    """For the operator's weekly pulse: what the free offer costs."""
    return budget.state(get_store())


# --- sources ---------------------------------------------------------------------------------------------------------

SECRET_KEYS = ("passwort", "schluessel", "token", "json")


def _public(source: dict) -> dict:
    out = {k: v for k, v in source.items() if not k.startswith("_") and not any(s in k for s in SECRET_KEYS)}
    return out | {"fehler": source.get("_fehler") or "", "letzter_abruf": source.get("_letzter_abruf")}


@app.put("/ki/quellen")
async def set_sources(request: Request, who: str = Depends(cockpit)) -> dict:
    """The cockpit pushes all sources at once (settings plus credentials from the vault); missing ones are removed.
    `mistral_schluessel`: the customer's own key (lifts the page cap); "" removes it, absent leaves it."""
    try:
        body = await request.json()
    except ValueError as e:
        raise Refusal(400, t("fehler.json")) from e
    sources = body.get("quellen") if isinstance(body, dict) else None
    if not isinstance(sources, list):
        raise Refusal(400, t("fehler.quellen_liste"))
    for s in sources:
        if not isinstance(s, dict) or not _SOURCE_ID.match(str(s.get("id") or "")):
            raise Refusal(400, t("fehler.quelle_id"))
        if s.get("art") not in intake.KINDS:
            raise Refusal(400, t("eingang.art_unbekannt", art=s.get("art") or "?"))
    store = get_store()
    store.set_sources(sources)
    if isinstance(body.get(budget.OWN_KEY), str):
        store.set_value(budget.OWN_KEY, body[budget.OWN_KEY].strip())
    store.log(who, t("protokoll.quellen", n=len(sources)))
    return {"quellen": [_public(s) for s in store.sources()], "seiten": budget.state(store)}


@app.get("/ki/quellen")
def sources(_: str = Depends(cockpit)) -> dict:
    store = get_store()
    return {"quellen": [_public(s) for s in store.sources()], "seiten": budget.state(store)}


@app.post("/ki/abgleich")
def sync_now(_: str = Depends(cockpit)) -> dict:
    """Fetch from the sources now (after `PUT ki/quellen`, to check them)."""
    store = get_store()
    counts = pipeline.intake_pass(store)
    return counts | {"quellen": [_public(s) for s in store.sources()]}


# --- vilikon.wissen/1 ------------------------------------------------------------------------------------------------

FILED = ("fertig", "pruefen")


def _file_name(doc: dict) -> str:
    day = doc["datum"] or doc["empfangen"][:10]
    words = re.sub(r"[\\/:*?\"<>|]+", " ", pipeline.title(doc)).strip()[:80]
    return f"{day} {words}.md"


def _markdown(doc: dict, deadlines: list[dict]) -> str:
    rows = [
        ("art", t(f"art.{doc['art']}")),
        ("absender", doc["absender"]),
        ("datum", doc["datum"]),
        ("aktenzeichen", doc["aktenzeichen"]),
        ("handlung", t(f"handlung.{doc['handlung']}") if doc["handlung"] else ""),
        ("betrag", f"{doc['betrag']:.2f} EUR" if doc["betrag"] is not None else ""),
    ]
    head = [f"# {pipeline.title(doc)}", ""] + [f"- {t(f'feld.{k}')}: {v}" for k, v in rows if v]
    head += [f"- {t('feld.frist')}: {f['datum']} ({t('frist.' + f['art'])})" for f in deadlines]
    return "\n".join([*head, "", "---", "", doc["text"]]) + "\n"


@app.get("/ki/wissen/dateien")
def knowledge_files(_: str = Depends(cockpit)) -> dict:
    """The whole list each time. Each letter as Markdown of its recognised text, so the cockpit does not run OCR a
    second time. `sensibel` and `meta` per file: the cockpit files confidential letters as confidential."""
    store = get_store()
    out = []
    for doc in store.documents(status=FILED):
        if not doc["text"].strip():
            continue
        name = _file_name(doc)
        year = (doc["datum"] or doc["empfangen"])[:4]
        out.append(
            {
                "id": doc["id"],
                "name": name,
                "pfad": f"{t('wissen.ordner')}/{year}/{name}",
                "version": f"{doc['sha256'][:12]}-{doc['geaendert']}",
                "groesse": len(_markdown(doc, store.deadlines(doc["id"])).encode()),
                "sensibel": bool(doc["vertraulich"]),
                "meta": {
                    "art": doc["art"],
                    "absender": doc["absender"],
                    "datum": doc["datum"],
                    "aktenzeichen": doc["aktenzeichen"],
                    "handlung": doc["handlung"],
                    "fristen": [f["datum"] for f in store.deadlines(doc["id"])],
                    "status": doc["status"],
                },
            }
        )
    return {"dateien": out}


@app.get("/ki/wissen/datei")
def knowledge_file(id: str, _: str = Depends(cockpit)):
    store = get_store()
    doc = store.document(id)
    if not doc or doc["status"] not in FILED:
        raise Refusal(404, t("fehler.dokument_fehlt"))
    return PlainTextResponse(_markdown(doc, store.deadlines(id)), media_type="text/markdown; charset=utf-8")


# --- phone -----------------------------------------------------------------------------------------------------------


@app.post("/api/upload")
async def upload(dateien: list[UploadFile] = File(...), who: str = Depends(person)) -> dict:
    """The pages of one letter, photographed on the phone (or one PDF shared into Vilikon)."""
    files = [(f.filename or "foto.jpg", await f.read()) for f in dateien]
    try:
        name, data = to_pdf(files)
    except UploadError as e:
        raise Refusal(400, str(e)) from e
    store = get_store()
    got = await run_in_threadpool(pipeline.receive, store, name, data, "handy", who)
    doc = got.document if got.duplicate else await run_in_threadpool(pipeline.process, store, got.document)
    return {
        "id": doc["id"],
        "doppelt": got.duplicate,
        "status": doc["status"],
        "text": t("upload.doppelt") if got.duplicate else t(f"upload.status_{doc['status']}"),
    }
