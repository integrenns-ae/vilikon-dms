"""Page cap and waiting queue, phone upload, file store adapters."""

import io
import os
import tempfile
import tracemalloc
from datetime import UTC, datetime

import pytest
from conftest import HOST_KEY, browser, filestore, letter, photo, recorded
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app import budget, config, pipeline, upload
from app.intake import IntakeError, sftp_ftp
from app.intake.env_sources import sources_from_env

LOGGED_IN = browser()

# --- budget ----------------------------------------------------------------------------------------------------------


def test_at_the_cap_documents_wait_and_go_on_next_month(cockpit, scanner, store, monkeypatch, fetch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    counts = fetch()
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


def test_a_customers_own_key_has_no_cap(cockpit, scanner, mistral, vault, fetch):
    # the customer's own vault entry: the same type, without OCR_BETREIBER and without a cap
    vault(OCR_PASSWORT="customer-key", OCR_BETREIBER=None, OCR_PAGES_PER_MONTH="1")
    assert fetch()["read"] == 3
    assert mistral.requests[-1]["_auth"] == "Bearer customer-key"
    pages = cockpit.get("ki/pages").json()
    assert pages["cap"] is None and pages["own_key"] is True
    assert budget.cap() == 0


def test_where_the_key_and_the_cap_come_from(env, vault):
    assert (budget.api_key(), budget.operator(), budget.cap()) == ("operator-key", True, 300)
    vault(OCR_PAGES_PER_MONTH=None, DMS_PAGES_PER_MONTH="7")
    assert budget.cap() == 7
    vault(DMS_PAGES_PER_MONTH=None)
    assert budget.cap() == 500
    vault(OCR_PAGES_PER_MONTH="0")
    assert budget.cap() == 0  # the operator's key without a cap
    # standalone: MISTRAL_API_KEY stands in, without a cap unless OCR_BETREIBER says it is the operator's
    vault(dict.fromkeys(("OCR_ART", "OCR_SERVICE", "OCR_PASSWORT", "OCR_BETREIBER", "OCR_PAGES_PER_MONTH")))
    vault(MISTRAL_API_KEY="standalone-key")
    assert (budget.api_key(), budget.cap()) == ("standalone-key", 0)
    vault(OCR_PASSWORT="vault-key")
    assert budget.api_key() == "vault-key"
    vault(OCR_SERVICE="openai")
    assert budget.api_key() == ""  # only Mistral reads letters


def test_without_any_key_documents_wait(cockpit, scanner, store, vault, fetch):
    vault(OCR_PASSWORT=None)
    fetch()
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
    files = [("files", ("a.jpg", photo(1), "image/jpeg"))]
    for headers in ({}, {"X-Vilikon-Benutzer": "erika@example.com"}, browser() | {"X-Vilikon-Token": "forged"}):
        r = client.post("/api/upload", files=files, headers=headers)
        assert r.status_code == 401 and r.json() == {"fehler": "Bitte im Cockpit anmelden."}


def test_upload_refuses_what_is_not_an_image(client):
    r = client.post("/api/upload", files=[("files", ("a.txt", b"hello", "text/plain"))], headers=LOGGED_IN)
    assert r.status_code == 400 and "a.txt" in r.json()["fehler"]
    mixed = [("files", ("a.pdf", letter(1), "application/pdf")), ("files", ("b.jpg", photo(1), "image/jpeg"))]
    assert client.post("/api/upload", files=mixed, headers=LOGGED_IN).status_code == 400


def test_the_phone_says_why_a_letter_is_not_read(client, mistral, monkeypatch):
    monkeypatch.setattr(config.settings, "pages_per_month", 2)
    thick = [("files", ("dick.pdf", letter(6, pages=3), "application/pdf"))]
    r = client.post("/api/upload", files=thick, headers=LOGGED_IN)
    assert r.json()["status"] == "error"
    assert r.json()["text"] == "Angekommen. Das Dokument hat mehr Seiten, als im Monat gelesen werden dürfen."
    assert mistral.requests == []


def test_a_shared_pdf_passes_as_it_is(client, mistral, store):
    mistral.default = recorded("advertising")
    pdf = letter(9)
    r = client.post("/api/upload", files=[("files", ("letter.pdf", pdf, "application/pdf"))], headers=LOGGED_IN)
    assert store.original(store.document(r.json()["id"])) == pdf


def _live_blocks() -> int:
    """Pillow's image memory, in blocks of 16 MB: tracemalloc does not see it."""
    stats = Image.core.get_stats()
    return stats["allocated_blocks"] - stats["freed_blocks"] - stats["blocks_cached"]


def test_thirty_pages_are_put_together_one_at_a_time(monkeypatch):
    out = io.BytesIO()
    page = Image.new("L", (2000, 2800), 235)
    ImageDraw.Draw(page).rectangle((200, 300, 1800, 2500), outline=20, width=12)
    page.convert("RGB").save(out, format="JPEG", quality=80)
    files = [(f"page{i}.jpg", io.BytesIO(out.getvalue())) for i in range(upload.MAX_PAGES)]
    live, real = [], upload._page

    def counted(name, f):
        part = real(name, f)
        live.append(_live_blocks())
        return part

    monkeypatch.setattr(upload, "_page", counted)
    before = _live_blocks()
    tracemalloc.start()
    try:
        name, pdf = upload.to_pdf(files)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert name == "scan.pdf" and len(PdfReader(io.BytesIO(pdf)).pages) == upload.MAX_PAGES
    # No decoded page outlives its turn: all 30 at once took 720 MB, one at a time 80 MB (resident, measured).
    assert set(live) == {before}
    assert peak < 25 * 1024 * 1024, peak  # what Python holds: the pages as PDF and pypdf's objects, about 12 MB


def test_a_turned_phone_photo_comes_out_upright_and_full_size():
    out, exif = io.BytesIO(), Image.Exif()
    exif[upload.ORIENTATION] = 6  # held upright, stored lying: 4000 × 3000
    Image.new("RGB", (4000, 3000), (240, 240, 240)).save(out, format="JPEG", exif=exif)
    _, pdf = upload.to_pdf([("upright.jpg", out)])
    box = PdfReader(io.BytesIO(pdf)).pages[0].mediabox
    assert (round(box.width / 72 * 200), round(box.height / 72 * 200)) == (2480, 3307)


def test_a_letter_and_a_photo_have_limits(client, monkeypatch):
    from app import main

    big = io.BytesIO()
    Image.new("L", (6400, 6400), 255).save(big, format="PNG")  # 41 megapixels, a small file
    r = client.post("/api/upload", files=[("files", ("huge.png", big.getvalue(), "image/png"))], headers=LOGGED_IN)
    assert r.status_code == 400 and r.json()["fehler"].startswith("„huge.png“ hat mehr als 40 Megapixel")
    four = [("files", (f"p{i}.jpg", photo(i), "image/jpeg")) for i in range(4)]
    with monkeypatch.context() as m:
        m.setattr(upload, "MAX_TOTAL", 3 * len(photo(3)))
        r = client.post("/api/upload", files=four, headers=LOGGED_IN)
    assert r.status_code == 400 and r.json()["fehler"].startswith("Zusammen höchstens")
    monkeypatch.setattr(main, "UPLOAD_LIMIT", 1000)  # refused by its Content-Length, before the body is read
    r = client.post("/api/upload", files=four, headers=LOGGED_IN)
    assert r.status_code == 413 and r.json() == {"fehler": "Zusammen höchstens 60 MB pro Brief."}


def test_temporary_files_stay_in_the_data_dir(env, mistral):
    from fastapi.testclient import TestClient

    from app.main import app

    tmp = config.settings.data_dir.resolve() / "tmp"
    tmp.mkdir(parents=True)
    (tmp / "left-by-a-crash").write_bytes(b"x")
    before = tempfile.gettempdir(), os.environ.get("TMPDIR")
    with TestClient(app):
        assert tempfile.gettempdir() == os.environ["TMPDIR"] == str(tmp)
        assert list(tmp.iterdir()) == []
    assert (tempfile.gettempdir(), os.environ.get("TMPDIR")) == before


# --- intake adapters -------------------------------------------------------------------------------------------------


def test_sources_from_the_environment():
    environ = (
        filestore()
        | filestore("SCANNER2", PROTOCOL="ftps", PORT="", MOVE_DONE="ja")
        | filestore("ARCHIVE", PROTOCOL="FTP", MOVE_DONE="false", PORT="2121")
        | {"OCR_ART": "api_key", "OCR_PASSWORT": "operator-key", "_ART": "filestore", "OTHER_ART": "login"}
    )
    found = {s["id"]: s for s in sources_from_env(environ)}
    assert list(found) == ["archive", "scanner", "scanner2"]
    assert found["scanner"] == {
        "id": "scanner",
        "kind": "sftp",
        "protocol": "sftp",
        "tls": True,
        "host": "nas.example.com",
        "port": 22,
        "user": "scan",
        "password": "secret-sftp",
        "folder": "/post",
        "move_done": False,
    }
    assert (found["scanner2"]["kind"], found["scanner2"]["tls"], found["scanner2"]["port"]) == ("ftp", True, None)
    assert found["scanner2"]["move_done"] is True
    assert (found["archive"]["kind"], found["archive"]["tls"], found["archive"]["port"]) == ("ftp", False, 2121)


def test_sftp_moves_done_files_when_the_source_says_so(cockpit, scanner, vault, fetch):
    vault(SCANNER_MOVE_DONE="true")
    fetch()
    assert sorted(p.name for p in (scanner.folder / "done").iterdir()) == [
        "scan_001.pdf",
        "scan_002.pdf",
        "scan_003.pdf",
    ]
    assert sorted(p.name for p in scanner.folder.iterdir() if p.is_file()) == [".hidden.pdf", "note.txt"]


def test_sftp_leaves_the_store_alone_by_default(cockpit, scanner, fetch):
    fetch()
    assert not (scanner.folder / "done").exists()


def test_ftp(cockpit, scanner, vault, fetch):
    vault(dict.fromkeys(filestore()))
    vault(filestore("SCANNER2", PROTOCOL="ftp", HOST="ftp.example.com", FOLDER="post", MOVE_DONE="1"))
    counts = fetch()
    assert counts["new"] == 3 and counts["errors"] == 0
    assert [s["id"] for s in counts["sources"]] == ["scanner2"]
    assert scanner.sources[-1]["tls"] is False
    assert len(list((scanner.folder / "done").iterdir())) == 3


def test_missing_folder_and_stores_not_yet_supported(cockpit, scanner, vault, fetch):
    vault(SCANNER_FOLDER="/missing")
    vault(filestore("SCANNER2", PROTOCOL="gdrive"), **filestore("SCANNER3", PROTOCOL="smb"))
    vault(filestore("SCANNER4", PROTOCOL=""))
    counts = fetch()
    assert counts["errors"] == 4
    state = {s["id"]: s["error"] for s in counts["sources"]}
    assert state["scanner"] == "Den Ordner „/missing“ gibt es in der Ablage nicht."
    assert state["scanner2"] == "Die Ablage „gdrive“ wird noch nicht unterstützt."
    assert state["scanner3"] == "Die Ablage „smb“ wird noch nicht unterstützt."
    assert state["scanner4"] == "Diese Art von Ablage kenne ich nicht: ?."


def test_a_failed_login_names_no_password(cockpit, scanner, vault, fetch):
    vault(SCANNER_PASSWORT="wrong")
    error = fetch()["sources"][0]["error"]
    assert error.startswith("Keine Verbindung zur SFTP-Ablage (AssertionError)") and "wrong" not in error


def test_the_sftp_host_key_is_trusted_on_first_use(cockpit, scanner, store, vault, fetch):
    assert fetch()["new"] == 3
    assert scanner.sources[-1]["host_key"] == ""  # the first time nothing is known
    assert store.source_states()["scanner"]["host_key"] == HOST_KEY
    (scanner.folder / "scan_004.pdf").write_bytes(letter(40))
    scanner.host_key = "ssh-ed25519 SHA256:someone-else"
    counts = fetch()
    assert counts["new"] == 0 and counts["errors"] == 1
    assert counts["sources"][0]["error"].startswith("Der SFTP-Server nas.example.com zeigt einen anderen Schlüssel")
    assert store.source_states()["scanner"]["host_key"] == HOST_KEY
    # another host (the owner changed the vault entry) is trusted anew
    vault(SCANNER_HOST="nas2.example.com")
    assert fetch()["new"] == 1
    assert store.source_states()["scanner"]["host_key"] == "ssh-ed25519 SHA256:someone-else"


class _Key:
    def __init__(self, blob: bytes) -> None:
        self.blob = blob

    def asbytes(self) -> bytes:
        return self.blob

    def get_name(self) -> str:
        return "ssh-ed25519"


def test_a_changed_host_key_ends_the_connection_before_the_password(monkeypatch):
    import paramiko

    sent = []

    class Transport:
        def __init__(self, sock) -> None:
            self.closed = False

        def start_client(self, timeout=None) -> None:
            pass

        def get_remote_server_key(self):
            return _Key(b"the-server-key")

        def auth_password(self, user, password) -> None:
            sent.append(password)

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(sftp_ftp.socket, "create_connection", lambda *a, **kw: object())
    monkeypatch.setattr(paramiko, "Transport", Transport)
    monkeypatch.setattr(paramiko.SFTPClient, "from_transport", classmethod(lambda cls, t: "client"))
    source = {"host": "nas.example.com", "port": 22, "user": "scan", "password": "secret-sftp", "host_key": ""}
    client, seen = sftp_ftp._sftp_connect(source)
    assert client == "client" and seen == sftp_ftp.fingerprint(_Key(b"the-server-key")) and sent == ["secret-sftp"]
    assert seen.startswith("ssh-ed25519 SHA256:") and not seen.endswith("=")
    with pytest.raises(IntakeError):
        sftp_ftp._sftp_connect(source | {"host_key": "ssh-ed25519 SHA256:another"})
    assert sent == ["secret-sftp"]


def test_the_store_forgets_what_the_cockpit_pushed_before(tmp_path):
    import sqlite3

    from app.store import Store

    db = sqlite3.connect(tmp_path / "dms.sqlite3")
    db.executescript(
        "CREATE TABLE sources (id TEXT PRIMARY KEY, data TEXT NOT NULL, error TEXT, last_fetch TEXT);"
        "CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);"
    )
    db.execute("INSERT INTO sources VALUES ('scanner', '{\"password\": \"secret-sftp-old\"}', '', NULL)")
    db.execute("INSERT INTO settings VALUES ('mistral_key', 'customer-key-old')")
    db.commit()
    db.close()
    store = Store(tmp_path)
    tables = {r["name"] for r in store._all("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "sources" not in tables and "settings" not in tables and "source_state" in tables
    files = b"".join(p.read_bytes() for p in tmp_path.glob("dms.sqlite3*"))
    assert b"secret-sftp-old" not in files and b"customer-key-old" not in files
