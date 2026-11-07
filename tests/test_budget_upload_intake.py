"""Page cap and waiting queue, phone upload, file store adapters."""

import io
from datetime import UTC, datetime

from conftest import SFTP_SOURCE, letter, photo, recorded
from pypdf import PdfReader

from app import budget, config, pipeline

LOGGED_IN = {"X-Vilikon-Benutzer": "erika@example.com"}

# --- budget ----------------------------------------------------------------------------------------------------------


def test_at_the_cap_documents_wait_and_go_on_next_month(cockpit, scanner, store, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    cockpit.push_sources([SFTP_SOURCE])
    counts = cockpit.sync_now()
    # scan_001 (1 page) is read, scan_002 (2 pages) would pass the cap: it and everything after it wait, in order
    assert counts["read"] == 1
    assert [d["status"] for d in store.documents()] == ["done", "waiting", "waiting"]
    assert store.documents()[1]["reason"] == "page_cap"
    assert cockpit.get("ki/pages").json() == {
        "month": budget.month(),
        "pages": 1,
        "cap": 2,
        "own_key": False,
        "waiting": 2,
    }
    assert cockpit.get("ki/karten/pages").json()["ton"] == "warn"

    monkeypatch.setattr(budget, "month", lambda at=None: "2099-01")
    assert pipeline.process_open(store) == 1  # the 2-page notice fits the new month, the next one waits again
    assert [d["status"] for d in store.documents()] == ["done", "done", "waiting"]


def test_an_own_key_lifts_the_cap(cockpit, scanner, store, mistral, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 1)
    cockpit.push_sources([SFTP_SOURCE], mistral_key="customer-key")
    assert cockpit.sync_now()["read"] == 3
    assert mistral.requests[-1]["_auth"] == "Bearer customer-key"
    state = cockpit.get("ki/sources").json()
    assert state["pages"]["cap"] is None and state["pages"]["own_key"] is True
    assert "customer-key" not in str(state)
    cockpit.push_sources([SFTP_SOURCE], mistral_key="")
    assert budget.cap(store) == 1


def test_without_any_key_documents_wait(cockpit, scanner, store, monkeypatch):
    monkeypatch.setattr(config.settings, "mistral_api_key", "")
    cockpit.push_sources([SFTP_SOURCE])
    cockpit.sync_now()
    assert {(d["status"], d["reason"]) for d in store.documents()} == {("waiting", "no_key")}


def test_a_document_larger_than_a_month_is_refused(store, mistral, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    got = pipeline.receive(store, "thick.pdf", letter(3, pages=3), "test")
    assert pipeline.process(store, got.document)["status"] == "error"
    assert mistral.requests == []


def test_ocr_failure_marks_the_document(store, mistral):
    mistral.fail = True
    got = pipeline.receive(store, "a.pdf", letter(4), "test")
    doc = pipeline.process(store, got.document)
    assert (doc["status"], doc["reason"]) == ("error", "ocr")
    assert store.pages_used(budget.month(datetime.now(UTC))) == 0


def test_long_documents_are_read_without_annotation(store, mistral):
    mistral.default = recorded("invoice")
    got = pipeline.receive(store, "long.pdf", letter(5, pages=9), "test")
    doc = pipeline.process(store, got.document)
    assert "document_annotation_format" not in mistral.requests[-1]
    assert (doc["status"], doc["reason"]) == ("review", "too_long") and doc["text"]


# --- phone upload ----------------------------------------------------------------------------------------------------


def test_photos_become_one_pdf(client, mistral, store):
    mistral.default = recorded("invoice")
    files = [("files", (f"page{i}.jpg", photo(i), "image/jpeg")) for i in range(3)]
    r = client.post("/api/upload", files=files, headers=LOGGED_IN)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done" and r.json()["duplicate"] is False
    doc = store.document(r.json()["id"])
    assert len(PdfReader(io.BytesIO(store.original(doc))).pages) == 3 and doc["source"] == "phone"
    again = client.post("/api/upload", files=files, headers=LOGGED_IN)
    assert again.json()["duplicate"] is True and again.json()["text"] == "Diesen Brief gibt es schon."
    assert len(mistral.requests) == 1


def test_upload_needs_a_login(client):
    r = client.post("/api/upload", files=[("files", ("a.jpg", photo(1), "image/jpeg"))])
    assert r.status_code == 401 and r.json() == {"fehler": "Bitte im Cockpit anmelden."}


def test_upload_refuses_what_is_not_an_image(client):
    r = client.post("/api/upload", files=[("files", ("a.txt", b"hello", "text/plain"))], headers=LOGGED_IN)
    assert r.status_code == 400 and "a.txt" in r.json()["fehler"]
    mixed = [("files", ("a.pdf", letter(1), "application/pdf")), ("files", ("b.jpg", photo(1), "image/jpeg"))]
    assert client.post("/api/upload", files=mixed, headers=LOGGED_IN).status_code == 400


def test_a_shared_pdf_passes_as_it_is(client, mistral, store):
    mistral.default = recorded("advertising")
    pdf = letter(9)
    r = client.post("/api/upload", files=[("files", ("letter.pdf", pdf, "application/pdf"))], headers=LOGGED_IN)
    assert store.original(store.document(r.json()["id"])) == pdf


# --- intake adapters -------------------------------------------------------------------------------------------------


def test_sftp_moves_done_files_when_the_source_says_so(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE | {"move_done": True}])
    cockpit.sync_now()
    assert sorted(p.name for p in (scanner.folder / "done").iterdir()) == [
        "scan_001.pdf",
        "scan_002.pdf",
        "scan_003.pdf",
    ]
    assert sorted(p.name for p in scanner.folder.iterdir() if p.is_file()) == [".hidden.pdf", "note.txt"]


def test_sftp_leaves_the_store_alone_by_default(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE])
    cockpit.sync_now()
    assert not (scanner.folder / "done").exists()


def test_ftp(cockpit, scanner):
    cockpit.push_sources([{"id": "ftp", "kind": "ftp", "host": "ftp.example.com", "folder": "post", "move_done": True}])
    counts = cockpit.sync_now()
    assert counts["new"] == 3 and counts["errors"] == 0
    assert len(list((scanner.folder / "done").iterdir())) == 3


def test_missing_folder_and_stores_not_yet_supported(cockpit, scanner):
    cockpit.push_sources(
        [
            SFTP_SOURCE | {"folder": "/missing"},
            {"id": "drive", "kind": "gdrive"},
            {"id": "nas", "kind": "smb", "host": "nas.example.com"},
            {"id": "off", "kind": "onedrive", "active": False},
        ]
    )
    counts = cockpit.sync_now()
    assert counts["errors"] == 3
    state = {s["id"]: s["error"] for s in counts["sources"]}
    assert state["scanner"] == "Den Ordner „/missing“ gibt es in der Ablage nicht."
    assert state["drive"] == "Die Ablage „gdrive“ wird noch nicht unterstützt."
    assert state["nas"] == "Die Ablage „smb“ wird noch nicht unterstützt."
    assert state["off"] == ""


def test_a_failed_login_names_no_password(cockpit, scanner):
    cockpit.push_sources([SFTP_SOURCE | {"password": "wrong"}])
    error = cockpit.sync_now()["sources"][0]["error"]
    assert error.startswith("Keine Verbindung zur SFTP-Ablage (AssertionError)") and "wrong" not in error
