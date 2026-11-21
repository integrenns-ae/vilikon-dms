"""Fetching in the background, the check for the IT Specialist, the card, and the owner's controls on the page."""

import time

from conftest import HOST_KEY, filestore
from fastapi.testclient import TestClient

from app import main

OWNER = {"X-Vilikon-Benutzer": "erika@example.com", "X-Vilikon-Rolle": "kunde"}
COLLEAGUE = {"X-Vilikon-Benutzer": "max@example.com", "X-Vilikon-Rolle": "mitarbeiter"}


def _wait_for_the_pass() -> None:
    assert main.pass_lock.acquire(timeout=30)
    main.pass_lock.release()


def test_sync_answers_at_once_and_one_pass_runs_at_a_time(cockpit, scanner, store):
    with main.pass_lock:  # a pass of the loop is running
        r = cockpit.client.post("/ki/sync", json={}, headers=cockpit.headers())
        assert r.status_code == 202
        assert r.json() == {"status": "running", "text": "Die Ablagen werden gerade schon abgeholt."}
    assert store.documents() == []
    assert cockpit.sync_now()["status"] == "started"
    assert len(store.documents()) == 3


def test_the_first_pass_comes_soon_after_the_start(env, scanner, store, vault, monkeypatch):
    monkeypatch.setattr(main, "FIRST_PASS_S", 0.05)
    vault(DMS_INTERVAL_MIN="10")
    with TestClient(main.app):
        for _ in range(100):
            if len(store.documents(status=("done",))) == 3:
                break
            time.sleep(0.05)
    assert len(store.documents(status=("done",))) == 3


def test_check_for_the_it_specialist(cockpit, scanner, vault):
    check = cockpit.get("ki/pruefen").json()
    assert check == {
        "ok": True,
        "text": "Texterkennung mit dem Schlüssel des Betreibers: 0 von 300 Seiten in diesem Monat gelesen. "
        "Alle Ablagen antworten (1).",
        "sources": [
            {
                "id": "scanner",
                "protocol": "sftp",
                "host": "nas.example.com",
                "ok": True,
                "error": "",
                "last_fetch": None,
            }
        ],
        "ocr": {"ok": True, "operator": True, "pages_used": 0, "cap": 300},
    }
    assert "secret-sftp" not in str(check) and "operator-key" not in str(check)

    vault(filestore("SCANNER2", PROTOCOL="ftps", HOST="ftp.example.com", FOLDER="/missing"))
    check = cockpit.get("ki/pruefen").json()
    assert check["ok"] is False and [s["ok"] for s in check["sources"]] == [True, False]
    assert check["sources"][1]["protocol"] == "ftps"
    assert check["text"].endswith("Ablage scanner2: Den Ordner „/missing“ gibt es in der Ablage nicht.")

    vault(dict.fromkeys(filestore("SCANNER2")), OCR_PASSWORT=None)
    check = cockpit.get("ki/pruefen").json()
    assert check["ok"] is False and check["ocr"]["ok"] is False
    assert check["text"].startswith("Für die Texterkennung fehlt der Schlüssel (Tresor-Eintrag OCR)")

    vault(dict.fromkeys(filestore()), OCR_PASSWORT="customer-key", OCR_BETREIBER=None)
    check = cockpit.get("ki/pruefen").json()
    assert check["ok"] is True and check["sources"] == []
    assert check["ocr"] == {"ok": True, "operator": False, "pages_used": 0, "cap": None}
    assert "ohne Seitengrenze" in check["text"] and "nur über das Hochladen vom Handy" in check["text"]


def test_the_check_waits_ten_seconds_at_most(cockpit, scanner, monkeypatch):
    from app.intake import sftp_ftp

    slow = sftp_ftp.CONNECT["sftp"]

    def hanging(source):
        time.sleep(0.5)
        return slow(source)

    monkeypatch.setitem(sftp_ftp.CONNECT, "sftp", hanging)
    monkeypatch.setattr(main, "CHECK_TIMEOUT_S", 0.1)
    started = time.monotonic()
    check = cockpit.get("ki/pruefen").json()
    assert time.monotonic() - started < 0.45
    assert check["sources"][0]["error"] == "Die Ablage hat nicht innerhalb von 0.1 Sekunden geantwortet."


def test_the_card_names_each_failing_file_store(cockpit, scanner, vault, fetch):
    fetch()
    assert cockpit.get("ki/karten/pages").json()["ton"] == "neutral"
    vault(SCANNER_FOLDER="/missing")
    vault(filestore("SCANNER2", PROTOCOL="smb"))
    fetch()
    card = cockpit.get("ki/karten/pages").json()
    assert card["ton"] == "kritisch"
    assert card["zeilen"][1:] == [
        {"text": "scanner: Den Ordner „/missing“ gibt es in der Ablage nicht.", "wert": "Fehler"},
        {"text": "scanner2: Die Ablage „smb“ wird noch nicht unterstützt.", "wert": "Fehler"},
    ]


def test_the_owner_fetches_now(client, scanner, store):
    assert client.post("/api/sync", headers=COLLEAGUE).status_code == 403
    page = client.get("/api/documents", headers=COLLEAGUE).json()
    assert page["owner"] is False and page["sources"] == []
    r = client.post("/api/sync", headers=OWNER)
    assert r.status_code == 200 and r.json()["text"].startswith("Die Ablagen werden jetzt")
    _wait_for_the_pass()
    assert len(store.documents()) == 3
    page = client.get("/api/documents", headers=OWNER).json()
    assert page["owner"] is True and page["sources"][0]["id"] == "scanner" and page["sources"][0]["last_fetch"]
    assert "Jetzt abholen" in client.get("/", headers=OWNER).text


def test_the_owner_accepts_a_new_host_key(client, scanner, store, fetch):
    fetch()
    scanner.host_key = "ssh-ed25519 SHA256:bmV1ZXItc2NobHVlc3NlbA"
    assert fetch()["errors"] == 1
    source = client.get("/api/documents", headers=OWNER).json()["sources"][0]
    assert source["host_key_new"] == scanner.host_key and "anderen Schlüssel" in source["error"]
    assert client.post("/api/sources/scanner/trust", headers=COLLEAGUE).status_code == 403
    assert client.post("/api/sources/other/trust", headers=OWNER).status_code == 404
    r = client.post("/api/sources/scanner/trust", headers=OWNER)
    assert r.status_code == 200 and r.json()["text"].startswith("Der neue Schlüssel gilt")
    _wait_for_the_pass()
    state = store.source_states()["scanner"]
    assert (state["host_key"], state["host_key_new"], state["error"]) == (scanner.host_key, "", "")
    assert client.post("/api/sources/scanner/trust", headers=OWNER).status_code == 404  # nothing left to accept


def test_a_passing_glitch_leaves_no_key_to_accept(scanner, store, fetch):
    fetch()
    scanner.host_key = "ssh-ed25519 SHA256:c29tZW9uZS1pbi1iZXR3ZWVu"
    fetch()
    assert store.source_states()["scanner"]["host_key_new"]
    scanner.host_key = HOST_KEY  # the real server again
    assert fetch()["errors"] == 0
    assert store.source_states()["scanner"]["host_key_new"] == ""
