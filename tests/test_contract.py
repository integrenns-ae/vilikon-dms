"""The service token on every ki/ call, what the DMS says about itself, and the page behind the cockpit's login."""

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


@pytest.mark.parametrize("auth", [None, "Bearer wrong", f"Token {TOKEN}", "Bearer "])
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
    assert client.get("/health").json()["ok"] is True


def test_module_description_passes_the_cores_check(cockpit):
    modul = cockpit.get("ki/modul").json()
    cockpit.check_module(modul)
    assert modul["schluessel"] == "dms"
    assert modul["menue"] == {"titel": "Post", "symbol": "FileText"}
    assert modul["anschluesse"] == [{"standard": "vilikon.wissen/1", "name": "Post", "intervall_min": 15}]
    assert {f["name"] for f in modul["funktionen"]} >= {"search_documents", "due_dates", "receipt_data"}
    # every function path and every card answers (no 404 for a path the module announces)
    for f in modul["funktionen"]:
        r = cockpit.get(f["pfad"].replace("{id}", "unknown"))
        assert r.status_code in (200, 404) and r.json() != {"fehler": "Diesen Pfad gibt es nicht."}, f["pfad"]
    for k in modul["karten"]:
        assert cockpit.get(k["pfad"]).status_code == 200
    assert "search_documents" in cockpit.get("ki/anleitung").text


def test_module_in_english(cockpit, monkeypatch):
    monkeypatch.setattr(config.settings, "language", "en")
    modul = cockpit.get("ki/modul").json()
    cockpit.check_module(modul)
    assert modul["name"] == "Mail"
    assert cockpit.get("ki/documents/x").json() == {"fehler": "This document does not exist."}


def test_errors_are_plain_words(cockpit):
    assert cockpit.get("ki/missing").json() == {"fehler": "Diesen Pfad gibt es nicht."}
    assert cockpit.client.put("/ki/sources", content=b"{", headers=cockpit.headers()).status_code == 400
    r = cockpit.push_sources([{"id": "Bad Id", "kind": "sftp"}])
    assert r.status_code == 400 and "id" in r.json()["fehler"]
    r = cockpit.push_sources([{"id": "a1", "kind": "fax"}])
    assert r.json() == {"fehler": "Diese Art von Ablage kenne ich nicht: fax."}


def test_events_are_not_lost_when_more_than_five_wait(cockpit, store):
    for i in range(7):
        store.add_event(f"e{i}", "pay", f"Pay {i}", "", None, {})
    first = cockpit.poll_events()
    second = cockpit.poll_events()
    assert len(first) == 5 and len(second) == 2
    assert {e["id"] for e in first + second} == {f"e{i}" for i in range(7)}
    assert cockpit.poll_events() == []


def test_page_behind_the_cockpit_login(client, store):
    assert client.get("/").status_code == 401
    browser = {
        "Authorization": f"Bearer {TOKEN}",
        "X-Vilikon-Benutzer": "erika@example.com",
        "X-Vilikon-Rolle": "kunde",
    }
    page = client.get("/", headers=browser)
    assert page.status_code == 200 and "<h1>Post</h1>" in page.text and 'fetch("api/upload"' in page.text
    for i, secret in enumerate((0, 1)):
        doc = store.add_document(sha=f"{i:064}", name=f"b{i}.pdf", source="test", suffix=".pdf", data=b"%PDF-", pages=1)
        store.update_document(
            doc["id"],
            status="review",
            reason="deadline_unclear",
            confidential=secret,
            kind="letter",
            sender="Amtsgericht Musterstadt" if secret else "Musterfirma GmbH",
        )
    owner = client.get("/api/documents", headers=browser).json()
    assert len(owner["review"]) == 2 and owner["review"][0]["reason"].startswith("Eine Frist")
    operator = client.get("/api/documents", headers=browser | {"X-Vilikon-Rolle": "betreiber"}).json()
    assert [d["title"] for d in operator["documents"]] == ["Musterfirma GmbH"]
