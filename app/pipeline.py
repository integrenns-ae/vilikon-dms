"""From bytes to a filed document: dedupe by sha256 → page budget → OCR and annotation → rules → case → events.

Status of a document: `neu` (just in), `wartet` (page cap or no key; goes on by itself), `fertig`, `pruefen` (a person
must look: `grund` says why), `fehler` (OCR failed or too big; `grund`)."""

from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from app import budget, ocr
from app.intake import IntakeError, open_adapter
from app.store import Store
from app.texte import t

log = logging.getLogger(__name__)

ITEMS_PER_PASS = 50
ACTION_EVENTS = ("zahlen", "antworten", "widersprechen", "frist")


@dataclass
class Received:
    document: dict
    duplicate: bool


def count_pages(name: str, data: bytes) -> int:
    if Path(name).suffix.lower() != ".pdf":
        return 1
    try:
        return max(1, len(PdfReader(io.BytesIO(data)).pages))
    except Exception:  # a broken PDF still goes to Mistral once; it counts as one page until then
        return 1


def receive(store: Store, name: str, data: bytes, source: str, who: str = "dms") -> Received:
    """Take a document in. The same bytes twice (a scan and a photo of the same file, a second pass) are one document."""
    sha = hashlib.sha256(data).hexdigest()
    found = store.by_sha(sha)
    if found:
        return Received(found, True)
    suffix = Path(name).suffix.lower() or ".pdf"
    doc = store.add_document(sha=sha, name=name, source=source, suffix=suffix, data=data, pages=count_pages(name, data))
    store.log(who, t("protokoll.eingang", name=name, quelle=source))
    return Received(doc, False)


def process(store: Store, doc: dict) -> dict:
    """Read one document if the budget allows. Returns it as it is now."""
    if not ocr.readable(doc["name"]):
        store.update_document(doc["id"], status="fehler", grund="format")
        return store.document(doc["id"]) or doc
    if budget.too_big(store, doc["seiten"]):
        store.update_document(doc["id"], status="fehler", grund="zu_gross")
        return store.document(doc["id"]) or doc
    key = budget.api_key(store)
    if not key or not budget.fits(store, doc["seiten"]):
        store.update_document(doc["id"], status="wartet", grund="kein_schluessel" if not key else "seitengrenze")
        return store.document(doc["id"]) or doc
    try:
        reading = ocr.read(doc["name"], store.original(doc), key, pages=doc["seiten"])
    except ocr.OcrError as e:
        log.warning("ocr failed for %s: %s", doc["id"], e)
        store.update_document(doc["id"], status="fehler", grund="ocr")
        return store.document(doc["id"]) or doc
    budget.book(store, reading.pages)
    fields, deadlines, reason = ocr.normalise(reading.fields)
    if not reading.fields and doc["seiten"] > ocr.ANNOTATION_MAX_PAGES:
        reason = "zu_lang"
    case_id = store.case_for(fields.get("aktenzeichen", ""), fields.get("absender", ""))
    store.update_document(
        doc["id"],
        **fields,
        text=reading.text,
        seiten=reading.pages,
        status="pruefen" if reason else "fertig",
        grund=reason,
        fall_id=case_id,
    )
    store.set_deadlines(doc["id"], deadlines)
    doc = store.document(doc["id"]) or doc
    _events(store, doc, deadlines)
    store.log("dms", t("protokoll.gelesen", titel=title(doc), art=t(f"art.{doc['art']}")))
    return doc


def title(doc: dict) -> str:
    return " – ".join(x for x in (doc.get("absender"), doc.get("betreff")) if x) or doc["name"]


def _data(doc: dict, deadlines: list[dict]) -> dict:
    return {
        "dokument_id": doc["id"],
        "art": doc["art"],
        "absender": doc["absender"],
        "betreff": doc["betreff"],
        "datum": doc["datum"],
        "aktenzeichen": doc["aktenzeichen"],
        "handlung": doc["handlung"],
        "betrag": doc["betrag"],
        "iban": doc["iban"],
        "verwendungszweck": doc["verwendungszweck"],
        "fristen": deadlines,
        "vertraulich": bool(doc["vertraulich"]),
        "fall_id": doc["fall_id"],
        "status": doc["status"],
        "grund": doc["grund"],
        "nur_inhaber": doc["art"] in ocr.ALWAYS_CONFIDENTIAL,
    }


def _deadline_text(deadlines: list[dict]) -> str:
    return "; ".join(f"{f['datum']} ({t('frist.' + f['art'])})" for f in deadlines) or t("frist.keine")


def _events(store: Store, doc: dict, deadlines: list[dict]) -> None:
    """Only what someone must do: each event becomes a case in the cockpit and, without a rule, costs a model run."""
    if doc["art"] == "werbung":
        return
    data, name = _data(doc, deadlines), title(doc)
    reason = t(f"grund.{doc['grund']}") if doc["grund"] else ""
    if doc["art"] in ocr.ALWAYS_CONFIDENTIAL:
        # Court and attorney post always ends with the owner, never at a rule's assignee.
        store.add_event(
            f"{doc['id']}-gericht",
            "gericht",
            t("ereignis.gericht_titel", titel=name)[:300],
            t("ereignis.gericht_text", fristen=_deadline_text(deadlines), grund=reason).strip(),
            doc["id"],
            data,
        )
    elif doc["status"] == "pruefen":
        store.add_event(
            f"{doc['id']}-pruefen", "pruefen", t("ereignis.pruefen_titel", titel=name)[:300], reason, doc["id"], data
        )
    elif doc["handlung"] in ACTION_EVENTS:
        amount = f"{doc['betrag']:.2f} EUR" if doc["betrag"] is not None else "–"
        store.add_event(
            f"{doc['id']}-{doc['handlung']}",
            doc["handlung"],
            t(f"ereignis.{doc['handlung']}_titel", titel=name)[:300],
            t("ereignis.handlung_text", betrag=amount, fristen=_deadline_text(deadlines)),
            doc["id"],
            data,
        )
    else:
        for i, f in enumerate(deadlines):
            store.add_event(
                f"{doc['id']}-{i}-frist",
                "frist_neu",
                t("ereignis.frist_neu_titel", titel=name, datum=f["datum"])[:300],
                t(f"frist.{f['art']}") + (f": {f['text']}" if f["text"] else ""),
                doc["id"],
                data | {"frist": f},
            )
    if doc["ist_beleg"]:
        store.add_event(
            f"{doc['id']}-beleg",
            "beleg",
            t("ereignis.beleg_titel", titel=name)[:300],
            t("ereignis.beleg_text"),
            doc["id"],
            data,
        )


def process_open(store: Store) -> int:
    """Documents that are new or waiting, oldest first; stops at the first one the budget does not allow, so the queue
    keeps its order. Returns how many were read."""
    n, queue = 0, store.documents(status=("neu", "wartet"))
    for i, doc in enumerate(queue):
        doc = process(store, doc)
        if doc["status"] == "wartet":
            for later in queue[i + 1 :]:
                store.update_document(later["id"], status="wartet", grund=doc["grund"])
            break
        n += 1
    return n


def intake_pass(store: Store) -> dict:
    """Fetch what is new in every source, then read what the budget allows."""
    counts = {"neu": 0, "doppelt": 0, "fehler": 0}
    for source in store.sources():
        if source.get("aktiv") is False:
            continue
        try:
            adapter = open_adapter(source)
        except IntakeError as e:
            store.source_state(source["id"], str(e))
            counts["fehler"] += 1
            continue
        error = ""
        try:
            todo = [i for i in adapter.list() if store.seen(source["id"], i.id) != i.version]
            for item in todo[:ITEMS_PER_PASS]:
                got = receive(store, item.name, adapter.fetch(item), source=source["id"])
                adapter.mark_done(item)
                store.mark_seen(source["id"], item.id, item.version)
                counts["doppelt" if got.duplicate else "neu"] += 1
        except IntakeError as e:
            error = str(e)
        except Exception as e:  # a broken connection in the middle: try again next pass
            error = t("eingang.abbruch", fehler=type(e).__name__)
        finally:
            adapter.close()
        store.source_state(source["id"], error)
        counts["fehler"] += bool(error)
    counts["gelesen"] = process_open(store)
    return counts
