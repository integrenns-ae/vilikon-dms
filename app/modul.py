"""What the DMS tells the cockpit about itself (`GET ki/modul`, standard vilikon.modul/1), in the instance's language."""

from __future__ import annotations

from app import VERSION
from app.texte import t

EVENTS = ("zahlen", "antworten", "widersprechen", "frist", "frist_neu", "gericht", "pruefen", "beleg")


def _function(name: str, right: str, path: str, properties: dict, required: tuple[str, ...] = ()) -> dict:
    params: dict = {"type": "object", "properties": properties}
    if required:
        params["required"] = list(required)
    return {
        "name": name,
        "beschreibung": t(f"funktion.{name}"),
        "recht": right,
        "methode": "GET",
        "pfad": path,
        "parameter": params,
    }


def _search_params() -> dict:
    return {
        "suche": {"type": "string", "description": t("parameter.suche")},
        "art": {"type": "string", "description": t("parameter.art")},
        "von": {"type": "string", "description": t("parameter.von")},
        "bis": {"type": "string", "description": t("parameter.bis")},
    }


def describe() -> dict:
    id_param = {"id": {"type": "string", "description": t("parameter.id")}}
    return {
        "standard": "vilikon.modul/1",
        "schluessel": "dms",
        "version": VERSION,
        "name": t("modul.name"),
        "beschreibung": t("modul.beschreibung"),
        "rechte": [
            {"key": "lesen", "titel": t("recht.lesen_titel"), "beschreibung": t("recht.lesen_text"), "sensibel": False},
            {
                "key": "vertraulich",
                "titel": t("recht.vertraulich_titel"),
                "beschreibung": t("recht.vertraulich_text"),
                "sensibel": True,
            },
            {
                "key": "belege",
                "titel": t("recht.belege_titel"),
                "beschreibung": t("recht.belege_text"),
                "sensibel": False,
            },
        ],
        "funktionen": [
            _function("dokument_suchen", "lesen", "ki/dokumente", _search_params()),
            _function("dokument_lesen", "lesen", "ki/dokumente/{id}", id_param, ("id",)),
            _function("vertrauliche_dokumente_suchen", "vertraulich", "ki/vertraulich/dokumente", _search_params()),
            _function(
                "vertrauliches_dokument_lesen", "vertraulich", "ki/vertraulich/dokumente/{id}", id_param, ("id",)
            ),
            _function(
                "fristen",
                "lesen",
                "ki/fristen",
                {
                    "von": {"type": "string", "description": t("parameter.von")},
                    "bis": {"type": "string", "description": t("parameter.bis")},
                },
            ),
            _function("beleg_daten", "belege", "ki/belege/{id}", id_param, ("id",)),
        ],
        "ereignisse": [
            {"art": e, "titel": t(f"ereignis.{e}"), "beschreibung": t(f"ereignis.{e}_beschreibung")} for e in EVENTS
        ],
        "ereignisse_intervall_min": 5,
        "karten": [
            {"titel": t("karte.post_titel"), "pfad": "ki/karten/post"},
            {"titel": t("karte.seiten_titel"), "pfad": "ki/karten/seiten"},
        ],
        "anschluesse": [
            {"standard": "vilikon.wissen/1", "name": t("modul.wissen_name"), "intervall_min": 15, "sensibel": False}
        ],
    }
