"""Fakes for everything outside the DMS: Mistral (recorded answers), the scanner's SFTP/FTP store and the cockpit."""

from __future__ import annotations

import base64
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


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


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
        import ftplib

        p = self._p(path)
        if not p.is_dir():
            raise ftplib.error_perm("550 no such directory")
        for f in sorted(p.iterdir()):
            yield (
                f.name,
                {"type": "dir" if f.is_dir() else "file", "size": str(f.stat().st_size), "modify": "20261102101200"},
            )

    def retrbinary(self, cmd: str, callback) -> None:
        callback(self._p(cmd.removeprefix("RETR ")).read_bytes())

    def mkd(self, path: str) -> None:
        import ftplib

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
    _PFAD = re.compile(r"^ki(/[A-Za-z0-9_\-][A-Za-z0-9_.\-]*|/\{[a-z_][a-z0-9_]*\})*/?$")

    def __init__(self, client: TestClient, token: str = TOKEN) -> None:
        self.client = client
        self.token = token
        self.seen_events: list[str] = []
        self.last_poll: str | None = None
        self.memory: dict[str, dict] = {}  # file id → {"version", "text", "sensibel", "meta"}

    def headers(self, who: str = "cockpit") -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Vilikon-Mitarbeiter": who,
            "X-Vilikon-Benutzer": f"{who}@mitarbeiter",
            "X-Vilikon-Rolle": "mitarbeiter",
        }

    def get(self, path: str, who: str = "cockpit", **params):
        return self.client.get("/" + path, params=params or None, headers=self.headers(who))

    def push_sources(self, sources: list[dict], **extra):
        return self.client.put("/ki/quellen", json={"quellen": sources, **extra}, headers=self.headers())

    def sync_now(self) -> dict:
        r = self.client.post("/ki/abgleich", headers=self.headers())
        assert r.status_code == 200, r.text
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
            assert self._NAME.match(f["name"]) and f["recht"] in rights and self._PFAD.match(f["pfad"]), f
            assert f["methode"] in ("GET", "POST", "PUT", "PATCH")
        for e in modul["ereignisse"]:
            assert self._NAME.match(e["art"]) and 0 < len(e["titel"]) <= 80 and len(e["beschreibung"]) <= 300, e
        assert len(modul["karten"]) <= 2
        for k in modul["karten"]:
            assert self._PFAD.match(k["pfad"]) and "{" not in k["pfad"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DMS_TOKEN", TOKEN)
    monkeypatch.setenv("MISTRAL_API_KEY", "operator-key")
    monkeypatch.setenv("DMS_INTERVALL_MIN", "0")
    monkeypatch.setenv("DMS_SEITEN_MONAT", "300")
    monkeypatch.delenv("DMS_SPRACHE", raising=False)
    config.reload()
    yield
    for k in ("DATA_DIR", "DMS_TOKEN", "MISTRAL_API_KEY", "DMS_INTERVALL_MIN", "DMS_SEITEN_MONAT"):
        os.environ.pop(k, None)
    config.reload()


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
def scanner(tmp_path, monkeypatch, mistral):
    """The scanner's SFTP folder `/post` with the three invented letters, each with its recorded Mistral answer."""
    root = tmp_path / "sftp"
    (root / "post").mkdir(parents=True)
    for i, name in enumerate(("rechnung", "bescheid", "werbung")):
        (root / "post" / f"scan_{i + 1:03}.pdf").write_bytes(
            mistral.answer(letter(i, 2 if name == "bescheid" else 1), recorded(name))
        )
    (root / "post" / ".hidden.pdf").write_bytes(b"%PDF-1.4")
    (root / "post" / "notiz.txt").write_text("not a letter")
    clients: list[FakeSftp] = []

    def connect(source):
        assert source["passwort"] == "geheim-sftp"
        clients.append(FakeSftp(root))
        return clients[-1]

    monkeypatch.setitem(sftp_ftp.CONNECT, "sftp", connect)
    monkeypatch.setitem(sftp_ftp.CONNECT, "ftp", lambda source: FakeFtp(root))
    return SimpleNamespace(root=root, folder=root / "post", clients=clients)


SFTP_SOURCE = {
    "id": "scanner",
    "art": "sftp",
    "host": "nas.example.com",
    "port": 22,
    "user": "scan",
    "passwort": "geheim-sftp",
    "ordner": "/post",
}
