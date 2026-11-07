"""The service token on every ki/ call, and what the DMS says about itself."""

import pytest
from conftest import TOKEN

from app import config


def _ki_routes():
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/ki/"):
            for method in route.methods - {"HEAD"}:
                yield method, path.replace("{doc_id}", "x")


@pytest.mark.parametrize("auth", [None, "Bearer falsch", f"Token {TOKEN}", "Bearer "])
def test_every_ki_call_needs_the_token(client, auth):
    routes = list(_ki_routes())
    assert len(routes) >= 15
    for method, path in routes:
        r = client.request(method, path, headers={"Authorization": auth} if auth else {})
        assert r.status_code == 401, (method, path)
        assert r.json() == {"fehler": "Nur das Cockpit darf das Modul aufrufen."}


def test_without_a_configured_token_nothing_is_open(client, monkeypatch):
    monkeypatch.setattr(config.settings, "token", "")
    assert client.get("/ki/modul", headers={"Authorization": "Bearer "}).status_code == 401


def test_health_needs_no_token(client):
    assert client.get("/gesund").json()["ok"] is True


def test_module_description_passes_the_cores_check(cockpit):
    modul = cockpit.get("ki/modul").json()
    cockpit.check_module(modul)
    assert modul["schluessel"] == "dms"
    assert {f["name"] for f in modul["funktionen"]} >= {"dokument_suchen", "fristen", "beleg_daten"}
    assert modul["anschluesse"][0]["standard"] == "vilikon.wissen/1"
    # every function path and every card answers (no 404 for a path the module announces)
    for f in modul["funktionen"]:
        r = cockpit.get(f["pfad"].replace("{id}", "unbekannt"))
        assert r.status_code in (200, 404) and r.json() != {"fehler": "Diesen Pfad gibt es nicht."}, f["pfad"]
    for k in modul["karten"]:
        assert cockpit.get(k["pfad"]).status_code == 200
    assert "dokument_suchen" in cockpit.get("ki/anleitung").text


def test_module_in_english(cockpit, monkeypatch):
    monkeypatch.setattr(config.settings, "language", "en")
    modul = cockpit.get("ki/modul").json()
    cockpit.check_module(modul)
    assert modul["name"] == "Mail"
    assert cockpit.get("ki/dokumente/x").json() == {"fehler": "This document does not exist."}


def test_errors_are_plain_words(cockpit):
    assert cockpit.get("ki/gibtsnicht").json() == {"fehler": "Diesen Pfad gibt es nicht."}
    assert cockpit.client.put("/ki/quellen", content=b"{", headers=cockpit.headers()).status_code == 400
    r = cockpit.push_sources([{"id": "Böse Id", "art": "sftp"}])
    assert r.status_code == 400 and "id" in r.json()["fehler"]
    r = cockpit.push_sources([{"id": "a1", "art": "faxgeraet"}])
    assert r.json() == {"fehler": "Diese Art von Ablage kenne ich nicht: faxgeraet."}


def test_events_are_not_lost_when_more_than_five_wait(cockpit, store):
    for i in range(7):
        store.add_event(f"e{i}", "zahlen", f"Zahlen {i}", "", None, {})
    first = cockpit.poll_events()
    second = cockpit.poll_events()
    assert len(first) == 5 and len(second) == 2
    assert {e["id"] for e in first + second} == {f"e{i}" for i in range(7)}
    assert cockpit.poll_events() == []
