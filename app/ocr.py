"""Reading a letter: Mistral OCR (`mistral-ocr-latest`) returns the text as Markdown and, through document annotation
with a JSON schema, what the letter is and what it wants. `normalise` then checks the answer against fixed rules, so a
model's guess never becomes a due date: court and attorney documents are always confidential, an unclear deadline
puts the document on the review list instead of into the calendar, and so does a receipt without sender, date or
amount instead of going to the bookkeeping."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx

from app import config

MISTRAL_URL = "https://api.mistral.ai/v1/ocr"
IMAGES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
ANNOTATION_MAX_PAGES = 8  # Mistral annotates a document as a whole only up to this many pages
TRANSPORT = None  # tests put an httpx.MockTransport here

KINDS = ("letter", "notice", "invoice", "reminder", "contract", "court", "attorney", "advertising", "other")
ACTIONS = ("pay", "reply", "object", "deadline", "none")
DUE_DATE_KINDS = ("payment", "tax", "objection", "reply", "court", "attorney", "appointment", "other")
ALWAYS_CONFIDENTIAL = ("court", "attorney")

_TEXT = {"type": "string"}
_NUMBER = {"type": ["number", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "kind",
        "subject",
        "sender",
        "date",
        "file_number",
        "action",
        "due_dates",
        "amount",
        "iban",
        "payment_reference",
        "is_receipt",
        "confidential",
    ],
    "properties": {
        "kind": {
            "type": "string",
            "enum": list(KINDS),
            "description": "What the document is. court: anything from a court (summons, decision, hearing date, "
            "statement of claim); attorney: a lawyer's letter; notice: a notice from an authority "
            "(tax office, social security); reminder: a payment reminder.",
        },
        "subject": {**_TEXT, "description": "The subject line or a short title of at most 80 characters."},
        "sender": {**_TEXT, "description": "Who sent it: company, authority or person, without the address."},
        "date": {**_TEXT, "description": "Date of the letter as YYYY-MM-DD, empty if none is printed."},
        "file_number": {
            **_TEXT,
            "description": "File number (Aktenzeichen), tax number, case or customer number, "
            "invoice number; empty if none.",
        },
        "action": {
            "type": "string",
            "enum": list(ACTIONS),
            "description": "What the recipient must do: pay, reply, object (to a notice), deadline (keep a date, "
            "e.g. a hearing), none.",
        },
        "due_dates": {
            "type": "array",
            "description": "Every date the document sets: payment days, tax due dates, objection periods, court and "
            "attorney dates, appointments. Only dates printed in the document; never compute one.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "date", "amount", "certain", "text"],
                "properties": {
                    "kind": {"type": "string", "enum": list(DUE_DATE_KINDS)},
                    "date": {**_TEXT, "description": "YYYY-MM-DD, empty if the document gives only a period."},
                    "amount": {**_NUMBER, "description": "Amount due on this date in EUR, null if none."},
                    "certain": {
                        "type": "boolean",
                        "description": "true only if this exact date is printed in the document.",
                    },
                    "text": {**_TEXT, "description": "The sentence that sets the date, shortened."},
                },
            },
        },
        "amount": {**_NUMBER, "description": "Total amount to pay in EUR, null if none."},
        "iban": {**_TEXT, "description": "IBAN to pay to, empty if none."},
        "payment_reference": {**_TEXT, "description": "Payment reference to use, empty if none."},
        "is_receipt": {"type": "boolean", "description": "true for an invoice or receipt the bookkeeping needs."},
        "confidential": {"type": "boolean", "description": "true for tax, salary, health, court and lawyer matters."},
    },
}


class OcrError(Exception):
    pass


@dataclass
class Reading:
    text: str
    pages: int
    fields: dict = field(default_factory=dict)  # empty when the document was not annotated


def readable(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix == ".pdf" or suffix in IMAGES


def read(name: str, data: bytes, api_key: str, *, pages: int) -> Reading:
    suffix = Path(name).suffix.lower()
    b64 = base64.b64encode(data).decode()
    if suffix == ".pdf":
        document = {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}
    else:
        document = {"type": "image_url", "image_url": f"data:{IMAGES.get(suffix, 'image/jpeg')};base64,{b64}"}
    body: dict = {"model": config.settings.mistral_ocr_model, "document": document, "include_image_base64": False}
    if pages <= ANNOTATION_MAX_PAGES:
        body["document_annotation_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "letter", "schema": SCHEMA, "strict": True},
        }
    try:
        with httpx.Client(timeout=300, transport=TRANSPORT) as c:
            r = c.post(MISTRAL_URL, headers={"Authorization": f"Bearer {api_key}"}, json=body)
        r.raise_for_status()
        answer = r.json()
    except (httpx.HTTPError, ValueError) as e:
        status = f" {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else ""
        raise OcrError(type(e).__name__ + status) from e
    text = "\n\n".join(p.get("markdown", "").strip() for p in answer.get("pages", []) if p.get("markdown", "").strip())
    processed = int((answer.get("usage_info") or {}).get("pages_processed") or len(answer.get("pages", [])) or pages)
    fields = answer.get("document_annotation") or {}
    if isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except ValueError:
            fields = {}
    return Reading(text=text, pages=processed, fields=fields if isinstance(fields, dict) else {})


def _iso(value) -> str:
    try:
        return date.fromisoformat(str(value or "").strip()).isoformat()
    except ValueError:
        return ""


def _amount(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def iban_ok(iban: str) -> bool:
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", iban):
        return False
    digits = "".join(str(int(c, 36)) for c in iban[4:] + iban[:4])
    return int(digits) % 97 == 1


def receipt_gap(doc: dict) -> str:
    """Why a receipt cannot go to the bookkeeping, as a reason key; "" when it can or it is none. The cockpit's receipt
    card needs the sender, the date and an amount above zero."""
    if not doc.get("is_receipt"):
        return ""
    amount = doc.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int | float) or amount <= 0:
        return "receipt_no_amount"
    if not str(doc.get("sender") or "").strip():
        return "receipt_no_sender"
    if not _iso(doc.get("date")):
        return "receipt_no_date"
    return ""


def normalise(fields: dict) -> tuple[dict, list[dict], str]:
    """(document fields, due dates, reason). An empty reason means done; any other is why a person must look
    (status `review`): an unclear due date, a court letter without one, a wrong IBAN, a receipt without sender, date
    or amount, no annotation at all."""
    if not fields:
        return {"kind": "other", "action": "none", "confidential": 0, "is_receipt": 0}, [], "no_fields"
    kind = fields.get("kind") if fields.get("kind") in KINDS else "other"
    action = fields.get("action") if fields.get("action") in ACTIONS else "none"
    out = {
        "kind": kind,
        "subject": str(fields.get("subject") or "").strip()[:200],
        "sender": str(fields.get("sender") or "").strip()[:200],
        "date": _iso(fields.get("date")),
        "file_number": str(fields.get("file_number") or "").strip()[:100],
        "action": action,
        "amount": _amount(fields.get("amount")),
        "iban": re.sub(r"\s", "", str(fields.get("iban") or "")).upper(),
        "payment_reference": str(fields.get("payment_reference") or "").strip()[:140],
        "is_receipt": int(bool(fields.get("is_receipt"))),
        "confidential": int(bool(fields.get("confidential")) or kind in ALWAYS_CONFIDENTIAL),
    }
    if kind == "advertising":
        return out | {"action": "none", "is_receipt": 0, "amount": None, "iban": ""}, [], ""
    due_dates, unclear = [], False
    for d in fields.get("due_dates") or []:
        if not isinstance(d, dict):
            continue
        day = _iso(d.get("date"))
        if not day or d.get("certain") is not True:
            unclear = True  # never guessed: a person looks at it
            continue
        due_dates.append(
            {
                "kind": d.get("kind") if d.get("kind") in DUE_DATE_KINDS else "other",
                "date": day,
                "amount": _amount(d.get("amount")),
                "text": str(d.get("text") or "").strip()[:300],
            }
        )
    reason = ""
    if unclear:
        reason = "deadline_unclear"
    elif kind in ALWAYS_CONFIDENTIAL and action != "none" and not due_dates:
        reason = "court_without_deadline"
    elif action == "deadline" and not due_dates:
        reason = "deadline_unclear"
    if out["iban"] and not iban_ok(out["iban"]):
        out["iban"], reason = "", reason or "iban_invalid"
    return out, due_dates, reason or receipt_gap(out)
