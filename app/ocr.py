"""Reading a letter: Mistral OCR (`mistral-ocr-latest`) returns the text as Markdown and, through document annotation
with a JSON schema, what the letter is and what it wants. `normalise` then checks the answer against fixed rules, so a
model's guess never becomes a deadline: court and attorney documents are always confidential, an unclear deadline
puts the document on the „prüfen“ list instead of into the calendar."""

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

KINDS = ("brief", "bescheid", "rechnung", "mahnung", "vertrag", "gericht", "anwalt", "werbung", "sonstiges")
ACTIONS = ("zahlen", "antworten", "widersprechen", "frist", "keine")
DEADLINE_KINDS = ("zahlung", "steuer", "widerspruch", "antwort", "gericht", "anwalt", "termin", "sonstiges")
ALWAYS_CONFIDENTIAL = ("gericht", "anwalt")

_TEXT = {"type": "string"}
_NUMBER = {"type": ["number", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "art",
        "betreff",
        "absender",
        "datum",
        "aktenzeichen",
        "handlung",
        "fristen",
        "betrag",
        "iban",
        "verwendungszweck",
        "ist_beleg",
        "vertraulich",
    ],
    "properties": {
        "art": {
            "type": "string",
            "enum": list(KINDS),
            "description": "What the document is. gericht: anything from a court (summons, decision, hearing date, "
            "statement of claim); anwalt: a lawyer's letter; bescheid: a notice from an authority "
            "(tax office, social security); mahnung: a payment reminder; werbung: advertising.",
        },
        "betreff": {**_TEXT, "description": "The subject line or a short title of at most 80 characters."},
        "absender": {**_TEXT, "description": "Who sent it: company, authority or person, without the address."},
        "datum": {**_TEXT, "description": "Date of the letter as YYYY-MM-DD, empty if none is printed."},
        "aktenzeichen": {
            **_TEXT,
            "description": "File number, tax number, case or customer number, invoice number; empty if none.",
        },
        "handlung": {
            "type": "string",
            "enum": list(ACTIONS),
            "description": "What the recipient must do: zahlen (pay), antworten (reply), widersprechen (object "
            "to it), frist (keep a date, e.g. a hearing), keine (nothing).",
        },
        "fristen": {
            "type": "array",
            "description": "Every date the document sets: payment days, tax due dates, objection periods, court and "
            "attorney dates, appointments. Only dates printed in the document; never compute one.",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["art", "datum", "betrag", "sicher", "text"],
                "properties": {
                    "art": {"type": "string", "enum": list(DEADLINE_KINDS)},
                    "datum": {**_TEXT, "description": "YYYY-MM-DD, empty if the document gives only a period."},
                    "betrag": {**_NUMBER, "description": "Amount due on this date in EUR, null if none."},
                    "sicher": {
                        "type": "boolean",
                        "description": "true only if this exact date is printed in the document.",
                    },
                    "text": {**_TEXT, "description": "The sentence that sets the date, shortened."},
                },
            },
        },
        "betrag": {**_NUMBER, "description": "Total amount to pay in EUR, null if none."},
        "iban": {**_TEXT, "description": "IBAN to pay to, empty if none."},
        "verwendungszweck": {**_TEXT, "description": "Payment reference to use, empty if none."},
        "ist_beleg": {"type": "boolean", "description": "true for an invoice or receipt the bookkeeping needs."},
        "vertraulich": {"type": "boolean", "description": "true for tax, salary, health, court and lawyer matters."},
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
            "json_schema": {"name": "brief", "schema": SCHEMA, "strict": True},
        }
    try:
        with httpx.Client(timeout=300, transport=TRANSPORT) as c:
            r = c.post(MISTRAL_URL, headers={"Authorization": f"Bearer {api_key}"}, json=body)
        r.raise_for_status()
        answer = r.json()
    except (httpx.HTTPError, ValueError) as e:
        raise OcrError(
            type(e).__name__ + (f" {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else "")
        ) from e
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


def normalise(fields: dict) -> tuple[dict, list[dict], str]:
    """(document fields, due dates, reason). An empty reason means done; any other is why a person must look
    („prüfen“): an unclear deadline, a court letter without one, a wrong IBAN, no annotation at all."""
    if not fields:
        return {"art": "sonstiges", "handlung": "keine", "vertraulich": 0, "ist_beleg": 0}, [], "keine_angaben"
    kind = fields.get("art") if fields.get("art") in KINDS else "sonstiges"
    action = fields.get("handlung") if fields.get("handlung") in ACTIONS else "keine"
    out = {
        "art": kind,
        "betreff": str(fields.get("betreff") or "").strip()[:200],
        "absender": str(fields.get("absender") or "").strip()[:200],
        "datum": _iso(fields.get("datum")),
        "aktenzeichen": str(fields.get("aktenzeichen") or "").strip()[:100],
        "handlung": action,
        "betrag": _amount(fields.get("betrag")),
        "iban": re.sub(r"\s", "", str(fields.get("iban") or "")).upper(),
        "verwendungszweck": str(fields.get("verwendungszweck") or "").strip()[:140],
        "ist_beleg": int(bool(fields.get("ist_beleg"))),
        "vertraulich": int(bool(fields.get("vertraulich")) or kind in ALWAYS_CONFIDENTIAL),
    }
    if kind == "werbung":
        return out | {"handlung": "keine", "ist_beleg": 0, "betrag": None, "iban": ""}, [], ""
    deadlines, unclear = [], False
    for f in fields.get("fristen") or []:
        if not isinstance(f, dict):
            continue
        day = _iso(f.get("datum"))
        if not day or f.get("sicher") is not True:
            unclear = True  # never guessed: a person looks at it
            continue
        deadlines.append(
            {
                "art": f.get("art") if f.get("art") in DEADLINE_KINDS else "sonstiges",
                "datum": day,
                "betrag": _amount(f.get("betrag")),
                "text": str(f.get("text") or "").strip()[:300],
            }
        )
    reason = ""
    if unclear:
        reason = "frist_unklar"
    elif kind in ALWAYS_CONFIDENTIAL and action != "keine" and not deadlines:
        reason = "gericht_ohne_frist"
    elif action == "frist" and not deadlines:
        reason = "frist_unklar"
    if out["iban"] and not iban_ok(out["iban"]):
        out["iban"], reason = "", reason or "iban_falsch"
    return out, deadlines, reason
