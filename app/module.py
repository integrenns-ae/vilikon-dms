"""What the DMS tells the cockpit about itself (`GET ki/modul`, standard vilikon.modul/1), in the instance's language.
The keys are the standard's (German); everything the DMS names itself is English."""

from __future__ import annotations

from app import VERSION
from app.texts import t

EVENTS = ("pay", "reply", "object", "deadline", "new_due_date", "court", "review", "receipt")


def _function(name: str, right: str, path: str, properties: dict, required: tuple[str, ...] = ()) -> dict:
    params: dict = {"type": "object", "properties": properties}
    if required:
        params["required"] = list(required)
    return {
        "name": name,
        "beschreibung": t(f"function.{name}"),
        "recht": right,
        "methode": "GET",
        "pfad": path,
        "parameter": params,
    }


def _string(key: str) -> dict:
    return {"type": "string", "description": t(f"parameter.{key}")}


def _search_params() -> dict:
    return {k: _string(k) for k in ("query", "kind", "from", "to")}


def _right(key: str, sensitive: bool) -> dict:
    return {"key": key, "titel": t(f"right.{key}_title"), "beschreibung": t(f"right.{key}_text"), "sensibel": sensitive}


def describe() -> dict:
    id_param = {"id": _string("id")}
    return {
        "standard": "vilikon.modul/1",
        "schluessel": "dms",
        "version": VERSION,
        "name": t("module.name"),
        "beschreibung": t("module.description"),
        "menue": {"titel": t("module.menu"), "symbol": "FileText"},
        "rechte": [_right("read", False), _right("confidential", True), _right("receipts", False)],
        "funktionen": [
            _function("search_documents", "read", "ki/documents", _search_params()),
            _function("read_document", "read", "ki/documents/{id}", id_param, ("id",)),
            _function("search_confidential_documents", "confidential", "ki/confidential/documents", _search_params()),
            _function(
                "read_confidential_document", "confidential", "ki/confidential/documents/{id}", id_param, ("id",)
            ),
            _function("due_dates", "read", "ki/due_dates", {"from": _string("from"), "to": _string("to")}),
            _function("receipt_data", "receipts", "ki/receipts/{id}", id_param, ("id",)),
        ],
        "ereignisse": [
            {"art": e, "titel": t(f"event.{e}"), "beschreibung": t(f"event.{e}_description")} for e in EVENTS
        ],
        "ereignisse_intervall_min": 5,
        "karten": [
            {"titel": t("card.mail_title"), "pfad": "ki/karten/mail"},
            {"titel": t("card.pages_title"), "pfad": "ki/karten/pages"},
        ],
        "anschluesse": [{"standard": "vilikon.wissen/1", "name": t("module.knowledge_name"), "intervall_min": 15}],
    }
