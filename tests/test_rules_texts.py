"""The fixed rules after Mistral's answer, and the texts in both languages."""

import re
import string

from app import ocr
from app.texte import dms_de, dms_en

BASE = {
    "art": "rechnung",
    "betreff": "Rechnung 1",
    "absender": "Musterfirma GmbH",
    "datum": "2026-11-02",
    "aktenzeichen": "RE-1",
    "handlung": "zahlen",
    "fristen": [],
    "betrag": 10,
    "iban": "",
    "verwendungszweck": "",
    "ist_beleg": True,
    "vertraulich": False,
}


def test_court_and_attorney_are_always_confidential():
    for kind in ("gericht", "anwalt"):
        fields, _, _ = ocr.normalise(BASE | {"art": kind, "handlung": "keine"})
        assert fields["vertraulich"] == 1


def test_a_deadline_is_never_guessed():
    deadline = {"art": "gericht", "datum": "2026-11-20", "betrag": None, "sicher": True, "text": ""}
    _, due, reason = ocr.normalise(BASE | {"art": "gericht", "handlung": "frist", "fristen": [deadline]})
    assert reason == "" and due[0]["datum"] == "2026-11-20"
    for unclear in ({"sicher": False}, {"datum": ""}, {"datum": "20.11.2026"}, {"datum": "2026-02-30"}):
        _, due, reason = ocr.normalise(BASE | {"art": "gericht", "handlung": "frist", "fristen": [deadline | unclear]})
        assert (due, reason) == ([], "frist_unklar"), unclear
    _, _, reason = ocr.normalise(BASE | {"art": "anwalt", "handlung": "antworten"})
    assert reason == "gericht_ohne_frist"


def test_advertising_asks_for_nothing():
    deadline = {"art": "sonstiges", "datum": "2026-11-30", "betrag": None, "sicher": True, "text": ""}
    fields, due, reason = ocr.normalise(BASE | {"art": "werbung", "fristen": [deadline], "iban": "DE00"})
    assert (fields["handlung"], fields["ist_beleg"], due, reason) == ("keine", 0, [], "")


def test_iban_is_checked():
    assert ocr.iban_ok("DE89370400440532013000")
    fields, _, reason = ocr.normalise(BASE | {"iban": "DE89 3704 0044 0532 0130 01"})
    assert fields["iban"] == "" and reason == "iban_falsch"


def test_unknown_values_fall_back_and_nothing_is_nothing():
    fields, _, _ = ocr.normalise(BASE | {"art": "fax", "handlung": "tanzen", "betrag": "viel", "datum": "gestern"})
    assert (fields["art"], fields["handlung"], fields["betrag"], fields["datum"]) == ("sonstiges", "keine", None, "")
    assert ocr.normalise({})[2] == "keine_angaben"


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
    assert ocr.SCHEMA["properties"]["art"]["enum"] == list(ocr.KINDS)


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f}


def test_both_languages_have_every_text_with_the_same_placeholders():
    assert set(dms_de.TEXTE) == set(dms_en.TEXTE)
    for key, de in dms_de.TEXTE.items():
        assert _fields(de) == _fields(dms_en.TEXTE[key]), key


def test_every_used_key_exists():
    from pathlib import Path

    source = "\n".join(p.read_text() for p in (Path(__file__).parent.parent / "app").rglob("*.py"))
    used = set(re.findall(r'\bt\(\s*"([a-z_]+\.[a-z_]+)"', source))
    assert used and used <= set(dms_de.TEXTE), used - set(dms_de.TEXTE)
    for prefix, values in (("art", ocr.KINDS), ("handlung", ocr.ACTIONS), ("frist", ocr.DEADLINE_KINDS)):
        for v in values:
            assert f"{prefix}.{v}" in dms_de.TEXTE
