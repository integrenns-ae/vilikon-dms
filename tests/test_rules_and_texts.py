"""The fixed rules after Mistral's answer, and the texts in both languages."""

import re
import string
from pathlib import Path

from app import ocr
from app.texts import de, en

BASE = {
    "kind": "invoice",
    "subject": "Rechnung 1",
    "sender": "Musterfirma GmbH",
    "date": "2026-11-02",
    "file_number": "RE-1",
    "action": "pay",
    "due_dates": [],
    "amount": 10,
    "iban": "",
    "payment_reference": "",
    "is_receipt": True,
    "confidential": False,
}


def test_court_and_attorney_are_always_confidential():
    for kind in ("court", "attorney"):
        fields, _, _ = ocr.normalise(BASE | {"kind": kind, "action": "none"})
        assert fields["confidential"] == 1


def test_a_due_date_is_never_guessed():
    due = {"kind": "court", "date": "2026-11-20", "amount": None, "certain": True, "text": ""}
    _, found, reason = ocr.normalise(BASE | {"kind": "court", "action": "deadline", "due_dates": [due]})
    assert reason == "" and found[0]["date"] == "2026-11-20"
    for unclear in ({"certain": False}, {"date": ""}, {"date": "20.11.2026"}, {"date": "2026-02-30"}):
        _, found, reason = ocr.normalise(BASE | {"kind": "court", "action": "deadline", "due_dates": [due | unclear]})
        assert (found, reason) == ([], "deadline_unclear"), unclear
    _, _, reason = ocr.normalise(BASE | {"kind": "attorney", "action": "reply"})
    assert reason == "court_without_deadline"


def test_advertising_asks_for_nothing():
    due = {"kind": "other", "date": "2026-11-30", "amount": None, "certain": True, "text": ""}
    fields, found, reason = ocr.normalise(BASE | {"kind": "advertising", "due_dates": [due], "iban": "DE00"})
    assert (fields["action"], fields["is_receipt"], found, reason) == ("none", 0, [], "")


def test_iban_is_checked():
    assert ocr.iban_ok("DE89370400440532013000")
    fields, _, reason = ocr.normalise(BASE | {"iban": "DE89 3704 0044 0532 0130 01"})
    assert fields["iban"] == "" and reason == "iban_invalid"


def test_a_receipt_needs_sender_date_and_amount():
    assert ocr.normalise(BASE)[2] == ""
    for gap, reason in (
        ({"amount": None}, "receipt_no_amount"),
        ({"amount": 0}, "receipt_no_amount"),
        ({"amount": -5}, "receipt_no_amount"),
        ({"sender": "  "}, "receipt_no_sender"),
        ({"date": ""}, "receipt_no_date"),
    ):
        assert ocr.normalise(BASE | gap)[2] == reason, gap
    assert ocr.normalise(BASE | {"amount": None, "is_receipt": False})[2] == ""
    assert ocr.normalise(BASE | {"amount": None, "iban": "DE00"})[2] == "iban_invalid"  # the first reason stays


def test_unknown_values_fall_back_and_nothing_is_nothing():
    fields, _, _ = ocr.normalise(BASE | {"kind": "fax", "action": "dance", "amount": "lots", "date": "yesterday"})
    assert (fields["kind"], fields["action"], fields["amount"], fields["date"]) == ("other", "none", None, "")
    assert ocr.normalise({})[2] == "no_fields"


def test_schema_is_strict():
    def walk(schema):
        if schema.get("type") == "object":
            assert schema["additionalProperties"] is False
            assert sorted(schema["required"]) == sorted(schema["properties"])
            for sub in schema["properties"].values():
                walk(sub)
        if schema.get("type") == "array":
            walk(schema["items"])

    walk(ocr.SCHEMA)
    assert ocr.SCHEMA["properties"]["kind"]["enum"] == list(ocr.KINDS)


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_both_languages_have_every_text_with_the_same_placeholders():
    assert set(de.TEXTS) == set(en.TEXTS)
    for key, german in de.TEXTS.items():
        assert _fields(german) == _fields(en.TEXTS[key]), key


def test_every_used_key_exists():
    source = "\n".join(p.read_text() for p in (Path(__file__).parent.parent / "app").rglob("*.py"))
    used = set(re.findall(r'\bt\(\s*"([a-z_]+\.[a-z_]+)"', source))
    assert used and used <= set(de.TEXTS), used - set(de.TEXTS)
    for prefix, values in (("kind", ocr.KINDS), ("action", ocr.ACTIONS), ("due", ocr.DUE_DATE_KINDS)):
        for v in values:
            assert f"{prefix}.{v}" in de.TEXTS
    for status in ("new", "waiting", "done", "review", "error"):
        assert f"upload.status_{status}" in de.TEXTS
