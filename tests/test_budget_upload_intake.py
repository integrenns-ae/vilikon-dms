"""Page cap and waiting queue, phone upload, file store adapters."""

import io
from datetime import UTC, datetime

from conftest import SFTP_SOURCE, letter, photo, recorded
from pypdf import PdfReader

from app import budget, config, pipeline

# --- budget ----------------------------------------------------------------------------------------------------------


def test_at_the_cap_documents_wait_and_go_on_next_month(cockpit, scanner, store, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    cockpit.push_sources([SFTP_SOURCE])
    counts = cockpit.sync_now()
    # scan_001 (1 page) is read, scan_002 (2 pages) would pass the cap: it and everything after it wait, in order
    assert counts["gelesen"] == 1
    assert [d["status"] for d in store.documents()] == ["fertig", "wartet", "wartet"]
    assert store.documents()[1]["grund"] == "seitengrenze"
    assert cockpit.get("ki/seiten").json() == {
        "monat": budget.month(),
        "seiten": 1,
        "grenze": 2,
        "eigener_schluessel": False,
        "wartend": 2,
    }
    assert cockpit.get("ki/karten/seiten").json()["ton"] == "warn"

    monkeypatch.setattr(budget, "month", lambda at=None: "2099-01")
    assert pipeline.process_open(store) == 1  # the 2-page notice fits the new month, the next one waits again
    assert [d["status"] for d in store.documents()] == ["fertig", "fertig", "wartet"]


def test_an_own_key_lifts_the_cap(cockpit, scanner, store, mistral, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 1)
    cockpit.push_sources([SFTP_SOURCE], mistral_schluessel="kunden-key")
    assert cockpit.sync_now()["gelesen"] == 3
    assert mistral.requests[-1]["_auth"] == "Bearer kunden-key"
    state = cockpit.get("ki/quellen").json()
    assert state["seiten"]["grenze"] is None and state["seiten"]["eigener_schluessel"] is True
    assert "kunden-key" not in str(state)
    cockpit.push_sources([SFTP_SOURCE], mistral_schluessel="")
    assert budget.cap(store) == 1


def test_without_any_key_documents_wait(cockpit, scanner, store, monkeypatch):
    monkeypatch.setattr(config.settings, "mistral_api_key", "")
    cockpit.push_sources([SFTP_SOURCE])
    cockpit.sync_now()
    assert {(d["status"], d["grund"]) for d in store.documents()} == {("wartet", "kein_schluessel")}


def test_a_document_larger_than_a_month_is_refused(store, mistral, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    got = pipeline.receive(store, "dick.pdf", letter(3, pages=3), "test")
    assert pipeline.process(store, got.document)["status"] == "fehler"
    assert mistral.requests == []


def test_ocr_failure_marks_the_document(store, mistral):
    mistral.fail = True
    got = pipeline.receive(store, "a.pdf", letter(4), "test")
    doc = pipeline.process(store, got.document)
    assert (doc["status"], doc["grund"]) == ("fehler", "ocr")
    assert store.pages_used(budget.month(datetime.now(UTC))) == 0


def test_long_documents_are_read_without_annotation(store, mistral):
    mistral.default = recorded("rechnung")
    got = pipeline.receive(store, "lang.pdf", letter(5, pages=9), "test")
    doc = pipeline.process(store, got.document)
    assert "document_annotation_format" not in mistral.requests[-1]
    assert (doc["status"], doc["grund"]) == ("pruefen", "zu_lang") and doc["text"]


# --- phone upload ----------------------------------------------------------------------------------------------------


def test_photos_become_one_pdf(client, mistral, store):
    mistral.default = recorded("rechnung")
    files = [("dateien", (f"seite{i}.jpg", photo(i), "image/jpeg")) for i in range(3)]
    r = client.post("/api/upload", files=files, headers={"X-Vilikon-Benutzer": "erika@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fertig" and r.json()["doppelt"] is False
    doc = store.document(r.json()["id"])
    assert len(PdfReader(io.BytesIO(store.original(doc))).pages) == 3 and doc["quelle"] == "handy"
    again = client.post("/api/upload", files=files, headers={"X-Vilikon-Benutzer": "erika@example.com"})
    assert again.json()["doppelt"] is True and again.json()["text"] == "Diesen Brief gibt es schon."
    assert len(mistral.requests) == 1


def test_upload_needs_a_login(client):
    r = client.post("/api/upload", files=[("dateien", ("a.jpg", photo(1), "image/jpeg"))])
    assert r.status_code == 401 and r.json() == {"fehler": "Bitte im Cockpit anmelden."}


def test_upload_refuses_what_is_not_an_image(client):
    headers = {"X-Vilikon-Benutzer": "erika@example.com"}
    r = client.post("/api/upload", files=[("dateien", ("a.txt", b"hallo", "text/plain"))], headers=headers)
    assert r.status_code == 400 and "a.txt" in r.json()["fehler"]
    mixed = [("dateien", ("a.pdf", letter(1), "application/pdf")), ("dateien", ("b.jpg", photo(1), "image/jpeg"))]
    assert client.post("/api/upload", files=mixed, headers=headers).status_code == 400


def test_a_shared_pdf_passes_as_it_is(client, mistral, store):
    mistral.default = recorded("werbung")
    pdf = letter(9)
    r = client.post(
        "/api/upload",
        files=[("dateien", ("brief.pdf", pdf, "application/pdf"))],
        headers={"X-Vilikon-Benutzer": "erika@example.com"},
    )
    assert store.original(store.document(r.json()["id"])) == pdf


# --- intake adapters -------------------------------------------------------------------------------------------------


def test_sftp_moves_done_files_when_the_source_says_so(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE | {"verschieben": True}])
    cockpit.sync_now()
    assert sorted(p.name for p in (scanner.folder / "erledigt").iterdir()) == [
        "scan_001.pdf",
        "scan_002.pdf",
        "scan_003.pdf",
    ]
    assert sorted(p.name for p in scanner.folder.iterdir() if p.is_file()) == [".hidden.pdf", "notiz.txt"]


def test_sftp_leaves_the_store_alone_by_default(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE])
    cockpit.sync_now()
    assert not (scanner.folder / "erledigt").exists()


def test_ftp(cockpit, scanner, store):
    cockpit.push_sources(
        [{"id": "ftp", "art": "ftp", "host": "ftp.example.com", "ordner": "post", "verschieben": True}]
    )
    counts = cockpit.sync_now()
    assert counts["neu"] == 3 and counts["fehler"] == 0
    assert len(list((scanner.folder / "erledigt").iterdir())) == 3


def test_missing_folder_and_stores_not_yet_supported(cockpit, scanner):
    cockpit.push_sources(
        [
            SFTP_SOURCE | {"ordner": "/fehlt"},
            {"id": "drive", "art": "gdrive"},
            {"id": "nas", "art": "smb", "host": "nas.example.com"},
            {"id": "aus", "art": "onedrive", "aktiv": False},
        ]
    )
    counts = cockpit.sync_now()
    assert counts["fehler"] == 3
    state = {q["id"]: q["fehler"] for q in counts["quellen"]}
    assert state["scanner"] == "Den Ordner „/fehlt“ gibt es in der Ablage nicht."
    assert state["drive"] == "Die Ablage „gdrive“ wird noch nicht unterstützt."
    assert state["nas"] == "Die Ablage „smb“ wird noch nicht unterstützt."
    assert state["aus"] == ""


def test_a_failed_login_names_no_password(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE | {"passwort": "falsch"}])
    counts = cockpit.sync_now()
    error = counts["quellen"][0]["fehler"]
    assert error.startswith("Keine Verbindung zur SFTP-Ablage (AssertionError)") and "falsch" not in error
