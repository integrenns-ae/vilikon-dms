"""The tool's token on every call, what the DMS says about itself, and the page behind the cockpit's login."""

import pytest
from conftest import TOKEN, browser

from app import config


def _ki_routes():
    from app.main import app

    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith("/ki/"):
            for method in route.methods - {"HEAD"}:
                yield method, path.replace("{doc_id}", "x")


FORGED = [
    {},
    {"X-Vilikon-Token": "wrong"},
    {"X-Vilikon-Token": ""},
    {"X-Vilikon-Token": TOKEN[:-1]},
    {"Authorization": f"Bearer {TOKEN}"},  # the Werkzeug has no DMS_TOKEN: a bearer token counts for nothing
    {"X-Vilikon-Mitarbeiter": "anna", "X-Vilikon-Benutzer": "erika@example.com", "X-Vilikon-Owner": "1"},
]


@pytest.mark.parametrize("headers", FORGED)
def test_every_ki_call_needs_the_token(client, headers):
    routes = list(_ki_routes())
    assert len(routes) >= 15
    for method, path in routes:
        r = client.request(method, path, headers=headers)
        assert r.status_code == 401, (method, path)
        assert r.json() == {"fehler": "Nur das Cockpit darf das Modul aufrufen."}


def test_standalone_the_bearer_token_counts(client, vault):
    vault(VILIKON_TOKEN=None, DMS_TOKEN="standalone-token")
    assert client.get("/ki/pages", headers={"Authorization": "Bearer standalone-token"}).status_code == 200
    assert client.get("/ki/pages", headers={"X-Vilikon-Token": "standalone-token"}).status_code == 401
    assert client.get("/ki/pages", headers={"X-Vilikon-Token": TOKEN}).status_code == 401


def test_without_a_configured_token_nothing_is_open(client, vault):
    vault(VILIKON_TOKEN=None, DMS_TOKEN=None)
    for headers in ({"X-Vilikon-Token": ""}, {"Authorization": "Bearer "}, {"Authorization": "Bearer"}):
        assert client.get("/ki/pages", headers=headers).status_code == 401
        assert client.get("/", headers=headers | {"X-Vilikon-Benutzer": "erika@example.com"}).status_code == 401


def test_health_needs_no_token(client):
    assert client.get("/health").json()["ok"] is True


def test_errors_are_plain_words(cockpit):
    assert cockpit.get("ki/missing").json() == {"fehler": "Diesen Pfad gibt es nicht."}
    # file stores come from the vault through the environment; nothing pushes them any more
    r = cockpit.client.put("/ki/sources", json={"sources": []}, headers=cockpit.headers())
    assert r.status_code in (404, 405) and r.json() == {"fehler": "Diesen Pfad gibt es nicht."}
    assert cockpit.get("ki/sources").status_code == 404


def test_events_are_not_lost_when_more_than_five_wait(cockpit, store):
    for i in range(7):
        store.add_event(f"e{i}", "pay", f"Pay {i}", "", None, {})
    first = cockpit.poll_events()
    second = cockpit.poll_events()
    assert len(first) == 5 and len(second) == 2
    assert {e["id"] for e in first + second} == {f"e{i}" for i in range(7)}
    assert cockpit.poll_events() == []


def test_page_behind_the_cockpit_login(client, store):
    owner = browser(owner=True, role="betreiber")  # the owner who set Vilikon up
    for forged in [*FORGED, {"X-Vilikon-Token": TOKEN}]:  # the token alone is no login either
        assert client.get("/", headers=forged).status_code == 401, forged
        assert client.get("/api/documents", headers=forged).json() == {"fehler": "Bitte im Cockpit anmelden."}
    page = client.get("/", headers=owner)
    assert page.status_code == 200 and '<html lang="de"><title>Post</title>' in page.text
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
    seen = client.get("/api/documents", headers=owner).json()
    assert len(seen["review"]) == 2 and seen["review"][0]["reason"].startswith("Eine Frist")
    for colleague in (
        browser("max@example.com"),
        browser("max@example.com", role="kunde"),
        owner | {"X-Vilikon-Owner": "0"},
    ):
        seen = client.get("/api/documents", headers=colleague).json()
        assert [d["title"] for d in seen["documents"]] == ["Musterfirma GmbH"]


def test_the_page_is_the_built_one_in_the_instances_language(client, ui, vault):
    page = client.get("/", headers=browser())
    assert page.headers["cache-control"] == "no-cache" and '<html lang="de"><title>Post</title>' in page.text
    script = client.get("/assets/index-abc1.js", headers=browser())
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert "immutable" in script.headers["cache-control"]
    assert client.get("/assets/index-abc1.js").status_code == 401
    (ui / "assets" / ".hidden").write_text("x")
    for name in ("missing.js", ".hidden"):
        assert client.get(f"/assets/{name}", headers=browser()).status_code == 404, name
    vault(VILIKON_LANGUAGE="en")
    assert '<html lang="en"><title>Mail</title>' in client.get("/", headers=browser()).text
    (ui / "index.html").unlink()
    page = client.get("/", headers=browser())
    assert page.status_code == 503 and page.json()["fehler"].startswith("The page is not built.")


def test_a_letter_opens_for_whom_the_list_shows_it(client, store):
    owner = browser(owner=True, role="betreiber")
    plain = store.add_document(sha="1" * 64, name="a.pdf", source="test", suffix=".pdf", data=b"%PDF-1.4 a", pages=1)
    secret = store.add_document(sha="2" * 64, name="b.pdf", source="test", suffix=".pdf", data=b"%PDF-1.4 b", pages=1)
    store.update_document(secret["id"], confidential=1)
    r = client.get(f"/api/documents/{plain['id']}/file", headers=browser())
    assert r.status_code == 200 and r.content == b"%PDF-1.4 a" and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == "inline" and r.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/documents/{secret['id']}/file", headers=browser()).status_code == 404
    assert client.get(f"/api/documents/{secret['id']}/file", headers=owner).content == b"%PDF-1.4 b"
    assert client.get(f"/api/documents/{plain['id']}/file").status_code == 401
    missing = client.get("/api/documents/unknown/file", headers=owner)
    assert missing.json() == {"fehler": "Dieses Dokument gibt es nicht."}


def test_the_language_comes_from_the_core(vault):
    vault(DMS_LANGUAGE="en")
    assert config.settings.language == "en"  # standalone
    vault(VILIKON_LANGUAGE="de")
    assert config.settings.language == "de"  # the instance's language wins
    vault(VILIKON_LANGUAGE="fr", DMS_LANGUAGE=None)
    assert config.settings.language == "de"
