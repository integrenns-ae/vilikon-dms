"""The files the core reads from the released repository: MODULE.json and BRIEFING.md (German, and English to swap in)
and ADAPTER.json. The checks follow the core's: backend/app/module.py `validate` (all or nothing: one bad field and
the whole module is dropped) and backend/app/adapters.py `parse_manifest`; lengths the core would cut are errors here."""

import json
import re
from pathlib import Path

import pytest

from app import config, module

ROOT = Path(__file__).parent.parent
ADAPTER = json.loads((ROOT / "ADAPTER.json").read_text())

KEY = re.compile(r"^[a-z][a-z0-9]{1,30}$")
NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
PATH = re.compile(r"^ki(/[A-Za-z0-9_\-][A-Za-z0-9_.\-]*|/\{[a-z_][a-z0-9_]*\})*/?$")
PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
METHODS = ("GET", "POST", "PUT", "PATCH")
ACCESS_NAME = re.compile(r"^[A-Z][A-Z0-9_]{1,40}$")
RESERVED = {"PATH", "HOME", "PORT", "HOST", "BASE_PATH", "DATA_DIR", "NODE_ENV", "LANG", "LC_ALL", "TZ"}
RESERVED |= {"PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE"}
RELATIVE = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]{1,200}$")
BRIEFINGS = {"de": ROOT / "BRIEFING.md", "en": ROOT / "vilikon" / "en" / "BRIEFING.md"}


def _text(value, limit: int) -> None:
    assert isinstance(value, str) and value.strip() and len(value) <= limit, (value, limit)
    assert " ".join(value.split()) == value, value  # the core folds whitespace


def check_module(m: dict) -> None:
    assert m["standard"] == "vilikon.modul/1" and KEY.match(m["schluessel"])
    _text(m["name"], 80)
    _text(m["beschreibung"], 300)
    rights = set()
    for r in m["rechte"]:
        assert NAME.match(r["key"]) and r["key"] not in rights and isinstance(r["sensibel"], bool), r
        _text(r["titel"], 80)
        _text(r["beschreibung"], 400)
        rights.add(r["key"])
    names = set()
    for f in m["funktionen"]:
        assert NAME.match(f["name"]) and f["name"] not in names, f
        assert f["methode"] in METHODS and PATH.match(f["pfad"]) and f["recht"] in rights, f
        _text(f["beschreibung"], 500)
        params = f["parameter"]
        assert params["type"] == "object" and "zusammenfassung" not in params["properties"], f
        assert all(p in params["properties"] for p in PLACEHOLDER.findall(f["pfad"])), f
        names.add(f["name"])
    _text(m["menue"]["titel"], 30)
    assert len(m["menue"]["symbol"]) <= 30
    kinds = set()
    for e in m["ereignisse"]:
        assert NAME.match(e["art"]) and e["art"] not in kinds, e
        _text(e["titel"], 80)
        _text(e["beschreibung"], 300)
        kinds.add(e["art"])
    assert 1 <= m["ereignisse_intervall_min"] <= 1440
    assert len(m["karten"]) <= 2
    for k in m["karten"]:
        _text(k["titel"], 60)
        assert PATH.match(k["pfad"]) and not PLACEHOLDER.search(k["pfad"]), k
    assert set(m) <= {"standard", "schluessel", "version", "name", "beschreibung", "menue", "rechte", "funktionen"} | {
        "ereignisse",
        "ereignisse_intervall_min",
        "karten",
        "anschluesse",
    }


@pytest.mark.parametrize("language", ["de", "en"])
def test_module_files_are_current_and_pass_the_cores_rules(language):
    path = module.FILES[language]
    assert path.read_text(encoding="utf-8") == module.render(language), "run: python -m app.module --write"
    m = json.loads(path.read_text(encoding="utf-8"))
    check_module(m)
    assert m["schluessel"] == "dms" and m["name"] == {"de": "Post", "en": "Mail"}[language]
    assert m["anschluesse"] == [{"standard": "vilikon.wissen/1", "name": m["name"], "intervall_min": 15}]


def test_the_setup_right_and_its_functions():
    m = json.loads(module.FILES["de"].read_text(encoding="utf-8"))
    setup = next(r for r in m["rechte"] if r["key"] == "setup")
    assert setup["sensibel"] is True and setup["titel"] == "Post einrichten"
    assert {(f["name"], f["methode"], f["pfad"]) for f in m["funktionen"] if f["recht"] == "setup"} == {
        ("sources_status", "GET", "ki/pruefen"),
        ("sync_now", "POST", "ki/sync"),
    }


def test_every_announced_path_answers(cockpit, monkeypatch):
    from app import main

    monkeypatch.setattr(config.settings, "language", "en")
    m = module.describe()
    for f in m["funktionen"]:
        r = cockpit.client.request(f["methode"], "/" + f["pfad"].replace("{id}", "unknown"), headers=cockpit.headers())
        assert r.status_code in (200, 202, 404) and r.json() != {"fehler": "This path does not exist."}, f["pfad"]
    for k in m["karten"]:
        assert cockpit.get(k["pfad"]).status_code == 200
    assert cockpit.get("ki/documents/x").json() == {"fehler": "This document does not exist."}
    assert main.pass_lock.acquire(timeout=30)  # the pass sync_now started
    main.pass_lock.release()


def test_the_module_no_longer_answers_for_itself(cockpit):
    for path in ("ki/modul", "ki/anleitung", "ki/sources"):
        assert cockpit.get(path).json() == {"fehler": "Diesen Pfad gibt es nicht."}, path


@pytest.mark.parametrize("language", ["de", "en"])
def test_briefing(language):
    text = BRIEFINGS[language].read_text(encoding="utf-8")
    assert 200 <= len(text) <= 8000  # the core's minimum for a briefing, and where it cuts
    for function in ("search_documents", "read_document", "due_dates", "receipt_data", "sources_status", "sync_now"):
        assert f"`{function}`" in text, function
    assert "`SCANNER`" in text and "`OCR`" in text
    assert {"de": "IT-Betreuer", "en": "IT Specialist"}[language] in text  # roles, never names


def test_adapter_manifest():
    a = ADAPTER
    assert a["standard"] == "vilikon.adapter/1" and a["slug"] == "dms"
    assert a["build"] == "python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
    assert a["start"] == ".venv/bin/python -m app"
    assert a["check"] == "ki/pruefen" and PATH.match(a["check"])
    for language in ("de", "en"):
        assert 0 < len(a["setup"][language]) <= 2000
    assert a["languages"] == {"en": {"MODULE.json": "vilikon/en/MODULE.json", "BRIEFING.md": "vilikon/en/BRIEFING.md"}}
    for files in a["languages"].values():
        for target, source in files.items():
            assert RELATIVE.match(target) and RELATIVE.match(source) and (ROOT / source).is_file()
    names = []
    for c in a["credentials"]:
        assert ACCESS_NAME.match(c["name"]) and c["name"] not in RESERVED, c
        assert c["art"] in ("geheim", "tresor") and (c["art"] == "geheim" or c["typ"]), c
        for field in ("label", "help"):
            assert set(c[field]) == {"de", "en"} and all(c[field].values()), (c["name"], field)
        names.append(c["name"])
    ocr, scanner = a["credentials"]
    assert (ocr["name"], ocr["typ"], ocr["operator"], ocr.get("optional", False)) == (
        "OCR",
        "api_key",
        "mistral",
        False,
    )
    assert (scanner["name"], scanner["typ"], scanner["optional"]) == ("SCANNER", "filestore", True)


def test_the_credentials_are_what_the_dms_reads(vault):
    from conftest import filestore

    from app import budget, pipeline

    # what the Verwalter makes of the two credentials of ADAPTER.json
    vault(OCR_ART="api_key", OCR_SERVICE="mistral", OCR_PASSWORT="vault-key")
    vault(filestore(), **filestore("SCANNER2"))
    assert budget.api_key() == "vault-key"
    assert [s["id"] for s in pipeline.sources()] == ["scanner", "scanner2"]
