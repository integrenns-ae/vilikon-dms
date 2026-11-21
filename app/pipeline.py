"""From bytes to a filed document: dedupe by sha256 → page budget → OCR and annotation → rules → case → events.

Status of a document: `new` (just in), `waiting` (page cap or no key; goes on by itself), `done`, `review` (a person
must look: `reason` says why), `error` (OCR failed or too big; `reason`).

The first fetch of a file store brings what lay there before (its backlog). A letter from it that is clearly old, dated
more than `DMS_ARCHIVE_DAYS` before the day it came in, is filed as archive: status `done`, reason `archive`,
searchable, but it announces nothing, so connecting a folder full of old scans does not flood the owner."""

from __future__ import annotations

import hashlib
import io
import logging
import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from pypdf import PdfReader

from app import budget, config, ocr
from app.intake import Adapter, HostKeyChanged, IntakeError, open_adapter
from app.intake.env_sources import sources_from_env
from app.store import Store, today
from app.texts import t

log = logging.getLogger(__name__)

ITEMS_PER_PASS = 50
ACTION_EVENTS = ("pay", "reply", "object", "deadline")
ARCHIVE = "archive"
# The tools share 1 GB: one letter at a time is put together from photos (upload.to_pdf) or sent to the OCR as base64.
HEAVY = threading.BoundedSemaphore(1)


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


def receive(store: Store, name: str, data: bytes, source: str, who: str = "dms", *, backlog: bool = False) -> Received:
    """Take a document in. The same bytes twice (a scan and a photo of the same file, a second pass) are one document.
    `backlog`: it comes from a file store's first fetch."""
    sha = hashlib.sha256(data).hexdigest()
    found = store.by_sha(sha)
    if found:
        return Received(found, True)
    suffix = Path(name).suffix.lower() or ".pdf"
    pages = count_pages(name, data)
    doc = store.add_document(sha=sha, name=name, source=source, suffix=suffix, data=data, pages=pages, backlog=backlog)
    store.log(who, t("log.received", name=name, source=source))
    return Received(doc, False)


def _set(store: Store, doc: dict, **fields) -> dict:
    store.update_document(doc["id"], **fields)
    return store.document(doc["id"]) or doc


def archived(doc: dict, letter_date: str) -> bool:
    """A letter from a file store's first fetch, dated more than `DMS_ARCHIVE_DAYS` before the day it came in."""
    days = config.settings.archive_days
    if not doc["backlog"] or days <= 0 or not letter_date:
        return False
    return date.fromisoformat(letter_date) < date.fromisoformat(doc["received_at"][:10]) - timedelta(days=days)


def process(store: Store, doc: dict) -> dict:
    """Read one document if the budget allows. Returns it as it is now."""
    if not ocr.readable(doc["name"]):
        return _set(store, doc, status="error", reason="format")
    if budget.too_big(doc["pages"]):
        return _set(store, doc, status="error", reason="too_big")
    key = budget.api_key()
    if not key or not budget.fits(store, doc["pages"]):
        return _set(store, doc, status="waiting", reason="no_key" if not key else "page_cap")
    try:
        with HEAVY:
            reading = ocr.read(doc["name"], store.original(doc), key, pages=doc["pages"])
    except ocr.OcrError as e:
        log.warning("ocr failed for %s: %s", doc["id"], e)
        return _set(store, doc, status="error", reason="ocr")
    budget.book(store, reading.pages)
    fields, due_dates, reason = ocr.normalise(reading.fields)
    if not reading.fields and doc["pages"] > ocr.ANNOTATION_MAX_PAGES:
        reason = "too_long"
    if archived(doc, fields.get("date", "")):
        reason = ARCHIVE  # whatever else is unclear in an old letter, nobody is asked about it
    case_id = store.case_for(fields.get("file_number", ""), fields.get("sender", ""))
    doc = _set(
        store,
        doc,
        **fields,
        text=reading.text,
        pages=reading.pages,
        status="done" if reason in ("", ARCHIVE) else "review",
        reason=reason,
        case_id=case_id,
    )
    store.set_due_dates(doc["id"], due_dates)
    _events(store, doc, due_dates)
    store.log("dms", t("log.read", title=title(doc), kind=t(f"kind.{doc['kind']}")))
    return doc


def title(doc: dict) -> str:
    return " – ".join(x for x in (doc.get("sender"), doc.get("subject")) if x) or doc["name"]


def _data(doc: dict, due_dates: list[dict]) -> dict:
    return {
        "document_id": doc["id"],
        "kind": doc["kind"],
        "sender": doc["sender"],
        "subject": doc["subject"],
        "date": doc["date"],
        "file_number": doc["file_number"],
        "action": doc["action"],
        "amount": doc["amount"],
        "iban": doc["iban"],
        "payment_reference": doc["payment_reference"],
        "due_dates": due_dates,
        "confidential": bool(doc["confidential"]),
        "case_id": doc["case_id"],
        "status": doc["status"],
        "reason": doc["reason"],
        "owner_only": doc["kind"] in ocr.ALWAYS_CONFIDENTIAL,
    }


def _due_date_text(due_dates: list[dict]) -> str:
    return "; ".join(f"{d['date']} ({t('due.' + d['kind'])})" for d in due_dates) or t("due.none")


def _events(store: Store, doc: dict, due_dates: list[dict]) -> None:
    """Only what someone must do: each event becomes a case in the cockpit and, without a rule, costs a model run.
    Advertising and an old letter from a file store's first fetch announce nothing; a day already past is no new due
    date; a receipt goes to the bookkeeping only with sender, date and amount (else the letter is on review)."""
    if doc["kind"] == "advertising" or doc["reason"] == ARCHIVE:
        return
    data, name = _data(doc, due_dates), title(doc)
    gap = ocr.receipt_gap(doc)
    reason = " ".join(t(f"reason.{r}") for r in dict.fromkeys(r for r in (doc["reason"], gap) if r))
    if doc["kind"] in ocr.ALWAYS_CONFIDENTIAL:
        # Court and attorney post always ends with the owner, never at a rule's assignee.
        text = t("event.court_text", due_dates=_due_date_text(due_dates), reason=reason).strip()
        store.add_event(f"{doc['id']}-court", "court", t("event.court_title", title=name)[:300], text, doc["id"], data)
    elif doc["status"] == "review":
        store.add_event(
            f"{doc['id']}-review", "review", t("event.review_title", title=name)[:300], reason, doc["id"], data
        )
    elif doc["action"] in ACTION_EVENTS:
        amount = f"{doc['amount']:.2f} EUR" if doc["amount"] is not None else "–"
        text = t("event.action_text", amount=amount, due_dates=_due_date_text(due_dates))
        store.add_event(
            f"{doc['id']}-{doc['action']}",
            doc["action"],
            t(f"event.{doc['action']}_title", title=name)[:300],
            text,
            doc["id"],
            data,
        )
    else:
        day = today().isoformat()
        for i, d in enumerate(due_dates):
            if d["date"] < day:
                continue
            text = t("due." + d["kind"]) + (f": {d['text']}" if d["text"] else "")
            store.add_event(
                f"{doc['id']}-{i}-due",
                "new_due_date",
                t("event.new_due_date_title", title=name, date=d["date"])[:300],
                text,
                doc["id"],
                data | {"due_date": d},
            )
    if doc["is_receipt"] and not gap:
        store.add_event(
            f"{doc['id']}-receipt",
            "receipt",
            t("event.receipt_title", title=name)[:300],
            t("event.receipt_text"),
            doc["id"],
            data,
        )


def process_open(store: Store) -> int:
    """Documents that are new or waiting, oldest first; at the first one the budget does not allow, the rest waits too,
    so the queue keeps its order. Returns how many were read."""
    n, queue = 0, store.documents(status=("new", "waiting"))
    for i, doc in enumerate(queue):
        doc = process(store, doc)
        if doc["status"] == "waiting":
            for later in queue[i + 1 :]:
                store.update_document(later["id"], status="waiting", reason=doc["reason"])
            break
        n += 1
    return n


def sources(environ: Mapping[str, str] | None = None) -> list[dict]:
    """The file stores the owner released for the DMS, as they are now."""
    return sources_from_env(os.environ if environ is None else environ)


def _where(source: dict) -> str:
    return f"{source.get('host')}:{source.get('port') or ''}"


def _place(source: dict) -> str:
    """Host, port and folder: pointed at another folder, a store has a first fetch again."""
    return _where(source) + (source.get("folder") or "")


def connect(store: Store, source: dict) -> Adapter:
    """Open a source's store. An SFTP server's key is trusted the first time per host and port, and must stay the same
    after that (the adapter refuses another one before the password goes out)."""
    state = store.source_states().get(source["id"]) or {}
    known = state.get("host_key", "") if state.get("host_key_for") == _where(source) else ""
    try:
        adapter = open_adapter(source | {"host_key": known})
    except HostKeyChanged as e:
        store.source_state(source["id"], str(e), fetched=False)
        store.set_new_host_key(source["id"], e.seen)
        raise
    if adapter.host_key and (adapter.host_key != known or state.get("host_key_new")):
        store.set_host_key(source["id"], _where(source), adapter.host_key)
    return adapter


def check_source(store: Store, source: dict) -> str:
    """A quick look into the folder: "" when the store answers, else what is wrong. Kept as the source's error, but
    not as a fetch."""
    error = ""
    try:
        adapter = connect(store, source)
        try:
            adapter.list()
        finally:
            adapter.close()
    except IntakeError as e:
        error = str(e)
    except Exception as e:
        error = t("intake.broken_off", error=type(e).__name__)
    store.source_state(source["id"], error, fetched=False)
    return error


def source_list(store: Store, environ: Mapping[str, str] | None = None) -> list[dict]:
    """Every source with what the last pass or check found: `{id, protocol, host, error, last_fetch, host_key_new}`,
    no secrets."""
    states = store.source_states()
    out = []
    for s in sources(environ):
        state = states.get(s["id"]) or {}
        out.append(
            {
                "id": s["id"],
                "protocol": s["protocol"],
                "host": s["host"],
                "error": state.get("error") or "",
                "last_fetch": state.get("last_fetch"),
                "host_key_new": state.get("host_key_new") or "",
            }
        )
    return out


def intake_pass(store: Store, environ: Mapping[str, str] | None = None) -> dict:
    """Fetch what is new in every source, then read what the budget allows. A source's first fetch lasts until all that
    lay in its folder has come in once (more than ITEMS_PER_PASS take several passes); what it brings is `backlog`."""
    counts = {"new": 0, "duplicate": 0, "errors": 0}
    for source in sources(environ):
        try:
            adapter = connect(store, source)
        except IntakeError as e:
            store.source_state(source["id"], str(e))
            counts["errors"] += 1
            continue
        error, place = "", _place(source)
        first = (store.source_states().get(source["id"]) or {}).get("caught_up") != place
        try:
            todo = [i for i in adapter.list() if store.seen(source["id"], i.id) != i.version]
            for item in todo[:ITEMS_PER_PASS]:
                got = receive(store, item.name, adapter.fetch(item), source=source["id"], backlog=first)
                adapter.mark_done(item)
                store.mark_seen(source["id"], item.id, item.version)
                counts["duplicate" if got.duplicate else "new"] += 1
            if first and len(todo) <= ITEMS_PER_PASS:
                store.set_caught_up(source["id"], place)
        except IntakeError as e:
            error = str(e)
        except Exception as e:  # a broken connection in the middle: try again next pass
            error = t("intake.broken_off", error=type(e).__name__)
        finally:
            adapter.close()
        store.source_state(source["id"], error)
        counts["errors"] += bool(error)
    counts["read"] = process_open(store)
    return counts
