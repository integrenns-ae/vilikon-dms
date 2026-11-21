"""Fakes for everything outside the DMS: Mistral (recorded answers), the scanner's SFTP/FTP store, the cockpit, and the
vault entries the Verwalter puts into the environment."""

from __future__ import annotations

import base64
import ftplib
import hashlib
import io
import json
import os
import re
import stat
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import config, ocr
from app.intake import sftp_ftp

TOKEN = "test-token-123"
FIXTURES = Path(__file__).parent / "fixtures" / "mistral"
HOST_KEY = "ssh-ed25519 SHA256:bXVzdGVyZmlybWEtbmFzLWtleQ"
SCANNER = {
    "PROTOCOL": "sftp",
    "HOST": "nas.example.com",
    "PORT": "22",
    "USER": "scan",
    "FOLDER": "/post",
    "PASSWORT": "secret-sftp",
}
# The vault entry OCR with the operator's key, as the Verwalter sets it.
OCR = {"OCR_ART": "api_key", "OCR_SERVICE": "mistral", "OCR_PASSWORT": "operator-key", "OCR_BETREIBER": "ja"}
OWN_PREFIXES = ("DMS_", "OCR_", "SCANNER", "VILIKON_", "MISTRAL_")


def filestore(name: str = "SCANNER", **fields) -> dict[str, str]:
    """The variables of a released vault entry of type filestore: `filestore(FOLDER="/missing")`."""
    values = SCANNER | {k.upper(): str(v) for k, v in fields.items()}
    return {f"{name}_ART": "filestore"} | {f"{name}_{k}": v for k, v in values.items()}


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def with_annotation(answer: dict, **changes) -> dict:
    """A recorded answer with some annotation fields changed."""
    return answer | {"document_annotation": json.dumps(json.loads(answer["document_annotation"]) | changes)}


def letter(seed: int, pages: int = 1) -> bytes:
    """A small PDF with `pages` pages; the seed makes the bytes differ."""
    imgs = [Image.new("RGB", (120 + seed, 170), (255, 255 - seed % 200, 255)) for _ in range(pages)]
    out = io.BytesIO()
    imgs[0].save(out, format="PDF", save_all=True, append_images=imgs[1:])
    return out.getvalue()


def photo(seed: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (90 + seed, 120), (200, seed % 255, 100)).save(out, format="JPEG")
    return out.getvalue()


class FakeMistral:
    """Answers by the sha256 of the document sent; `default` for anything else. Keeps the requests."""

    def __init__(self) -> None:
        self.answers: dict[str, dict] = {}
        self.default: dict | None = None
        self.requests: list[dict] = []
        self.fail = False

    def answer(self, data: bytes, response: dict) -> bytes:
        self.answers[hashlib.sha256(data).hexdigest()] = response
        return data

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body | {"_auth": request.headers.get("authorization")})
        if self.fail:
            return httpx.Response(500, json={"message": "down"})
        doc = body["document"]
        url = doc.get("document_url") or doc.get("image_url")
        data = base64.b64decode(url.split(",", 1)[1])
        found = self.answers.get(hashlib.sha256(data).hexdigest(), self.default)
        if found is None:
            return httpx.Response(422, json={"message": "unknown document"})
        if "document_annotation_format" not in body:
            found = found | {"document_annotation": None}
        return httpx.Response(200, json=found)


class FakeSftp:
    """What the adapter uses of paramiko's SFTPClient, on a local folder."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.closed = False

    def _p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def listdir_attr(self, path: str):
        p = self._p(path)
        if not p.is_dir():
            raise FileNotFoundError(path)
        out = []
        for f in sorted(p.iterdir()):
            st = f.stat()
            out.append(SimpleNamespace(filename=f.name, st_mode=st.st_mode, st_size=st.st_size, st_mtime=st.st_mtime))
        return out

    def open(self, path: str, mode: str = "rb"):
        return self._p(path).open(mode)

    def stat(self, path: str):
        p = self._p(path)
        if not p.exists():
            raise FileNotFoundError(path)
        return SimpleNamespace(st_mode=stat.S_IFDIR if p.is_dir() else stat.S_IFREG)

    def mkdir(self, path: str) -> None:
        self._p(path).mkdir()

    def rename(self, old: str, new: str) -> None:
        self._p(old).rename(self._p(new))

    def close(self) -> None:
        self.closed = True


class FakeFtp:
    """What the adapter uses of ftplib.FTP, on a local folder."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _p(self, path: str) -> Path:
        return self.root / path.lstrip("/")

    def mlsd(self, path: str, facts=()):
        p = self._p(path)
        if not p.is_dir():
            raise ftplib.error_perm("550 no such directory")
        for f in sorted(p.iterdir()):
            kind = "dir" if f.is_dir() else "file"
            yield f.name, {"type": kind, "size": str(f.stat().st_size), "modify": "20261102101200"}

    def retrbinary(self, cmd: str, callback) -> None:
        callback(self._p(cmd.removeprefix("RETR ")).read_bytes())

    def mkd(self, path: str) -> None:
        if self._p(path).exists():
            raise ftplib.error_perm("550 exists")
        self._p(path).mkdir()

    def rename(self, old: str, new: str) -> None:
        self._p(old).rename(self._p(new))

    def quit(self) -> None:
        pass

    def close(self) -> None:
        pass


class FakeCockpit:
    """Calls the DMS the way the core does (backend/app/product_modules.py, module.py, knowledge_sources.py)."""

    _NAME = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
    _PATH = re.compile(r"^ki(/[A-Za-z0-9_\-][A-Za-z0-9_.\-]*|/\{[a-z_][a-z0-9_]*\})*/?$")

    def __init__(self, client: TestClient, token: str = TOKEN) -> None:
        self.client = client
        self.token = token
        self.seen_events: list[str] = []
        self.last_poll: str | None = None
        self.memory: dict[str, dict] = {}  # file id → {"version", "text", "sensibel", "meta", "pfad"}

    def headers(self, who: str = "cockpit") -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Vilikon-Mitarbeiter": who,
            "X-Vilikon-Benutzer": f"{who}@mitarbeiter",
            "X-Vilikon-Rolle": "mitarbeiter",
        }

    def get(self, path: str, who: str = "cockpit", **params):
        return self.client.get("/" + path, params=params or None, headers=self.headers(who))

    def sync_now(self) -> dict:
        """`POST ki/sync` like the core (it answers at once), then wait for the pass in the background."""
        from app import main

        r = self.client.post("/ki/sync", json={}, headers=self.headers())
        assert r.status_code == 202, r.text
        assert main.pass_lock.acquire(timeout=30)
        main.pass_lock.release()
        return r.json()

    def poll_events(self) -> list[dict]:
        """At most 5 per fetch, each id once, `seit` moves to the time of this poll."""
        from app.store import now

        r = self.get("ki/ereignisse", **({"seit": self.last_poll} if self.last_poll else {}))
        assert r.status_code == 200, r.text
        self.last_poll = now()
        taken = []
        for e in r.json()["ereignisse"][:50]:
            if e["id"] in self.seen_events or len(taken) >= 5:
                continue
            self.seen_events.append(e["id"])
            taken.append(e)
        return taken

    def sync_knowledge(self) -> dict:
        r = self.get("ki/wissen/dateien")
        assert r.status_code == 200, r.text
        listed = {f["id"]: f for f in r.json()["dateien"]}
        for gone in [x for x in self.memory if x not in listed]:
            del self.memory[gone]
        for fid, f in listed.items():
            if self.memory.get(fid, {}).get("version") == f["version"]:
                continue
            got = self.get("ki/wissen/datei", id=fid)
            assert got.status_code == 200, got.text
            self.memory[fid] = {
                "version": f["version"],
                "text": got.text,
                "sensibel": f["sensibel"],
                "meta": f["meta"],
                "pfad": f["pfad"],
            }
        return self.memory

    def check_module(self, modul: dict) -> None:
        """The parts of the core's MODUL.json check (module.py) the DMS could get wrong."""
        assert modul["standard"] == "vilikon.modul/1" and self._NAME.match(modul["schluessel"])
        rights = {r["key"] for r in modul["rechte"]}
        for f in modul["funktionen"]:
            assert self._NAME.match(f["name"]) and f["recht"] in rights and self._PATH.match(f["pfad"]), f
            assert f["methode"] in ("GET", "POST", "PUT", "PATCH")
        for e in modul["ereignisse"]:
            assert self._NAME.match(e["art"]) and 0 < len(e["titel"]) <= 80 and len(e["beschreibung"]) <= 300, e
        assert len(modul["karten"]) <= 2
        for k in modul["karten"]:
            assert self._PATH.match(k["pfad"]) and "{" not in k["pfad"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in list(os.environ):
        if k.startswith(OWN_PREFIXES) or k == "DATA_DIR":
            monkeypatch.delenv(k)
    for k, v in (OCR | {"OCR_PAGES_PER_MONTH": "300", "DMS_INTERVAL_MIN": "0", "DMS_TOKEN": TOKEN}).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    config.reload()
    yield
    monkeypatch.undo()
    config.reload()


@pytest.fixture
def vault(env, monkeypatch):
    """Release vault entries (or drop them: `vault(SCANNER_ART=None)`), as the Verwalter does on a restart."""

    def release(variables: dict | None = None, **more) -> None:
        for k, v in {**(variables or {}), **more}.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, str(v))
        config.reload()

    return release


@pytest.fixture
def mistral(env, monkeypatch) -> FakeMistral:
    fake = FakeMistral()
    monkeypatch.setattr(ocr, "TRANSPORT", httpx.MockTransport(fake.handler))
    return fake


@pytest.fixture
def client(env, mistral):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def cockpit(client) -> FakeCockpit:
    return FakeCockpit(client)


@pytest.fixture
def store(env):
    from app.main import get_store

    return get_store()


@pytest.fixture
def fetch(store):
    """One pass right here, with what it found: what the background pass does after `POST ki/sync`."""
    from app import pipeline

    return lambda: pipeline.intake_pass(store) | {"sources": pipeline.source_list(store)}


@pytest.fixture
def scanner(tmp_path, monkeypatch, mistral, vault):
    """The scanner's SFTP folder `/post` with the three invented letters, each with its recorded Mistral answer, released
    to the DMS as the vault entry SCANNER. `host_key` is the key the fake server shows."""
    root = tmp_path / "sftp"
    (root / "post").mkdir(parents=True)
    for i, name in enumerate(("invoice", "tax_notice", "advertising")):
        data = letter(i, 2 if name == "tax_notice" else 1)
        (root / "post" / f"scan_{i + 1:03}.pdf").write_bytes(mistral.answer(data, recorded(name)))
    (root / "post" / ".hidden.pdf").write_bytes(b"%PDF-1.4")
    (root / "post" / "note.txt").write_text("not a letter")
    state = SimpleNamespace(root=root, folder=root / "post", clients=[], host_key=HOST_KEY, sources=[])

    def connect(source):
        state.sources.append(source)
        if source["host_key"] and source["host_key"] != state.host_key:
            raise sftp_ftp.HostKeyChanged(sftp_ftp.t("intake.host_key_changed", host=source["host"]), state.host_key)
        assert source["password"] == "secret-sftp"
        state.clients.append(FakeSftp(root))
        return state.clients[-1], state.host_key

    def connect_ftp(source):
        state.sources.append(source)
        return FakeFtp(root), ""

    monkeypatch.setitem(sftp_ftp.CONNECT, "sftp", connect)
    monkeypatch.setitem(sftp_ftp.CONNECT, "ftp", connect_ftp)
    vault(filestore())
    return state
