"""SQLite under $DATA_DIR: documents with what was read from them, due dates, cases by file number, events for the
cockpit, the log, page counts, sources. Originals lie beside it in `originale/`. One connection, one lock: the DMS
handles a handful of letters a day."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS dokumente (
    id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, name TEXT NOT NULL, quelle TEXT NOT NULL, endung TEXT NOT NULL,
    empfangen TEXT NOT NULL, geaendert TEXT NOT NULL, seiten INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL, grund TEXT NOT NULL DEFAULT '',
    art TEXT NOT NULL DEFAULT '', betreff TEXT NOT NULL DEFAULT '', absender TEXT NOT NULL DEFAULT '',
    datum TEXT NOT NULL DEFAULT '', aktenzeichen TEXT NOT NULL DEFAULT '', handlung TEXT NOT NULL DEFAULT '',
    betrag REAL, iban TEXT NOT NULL DEFAULT '', verwendungszweck TEXT NOT NULL DEFAULT '',
    ist_beleg INTEGER NOT NULL DEFAULT 0, vertraulich INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '', fall_id TEXT
);
CREATE TABLE IF NOT EXISTS fristen (
    id TEXT PRIMARY KEY, dokument_id TEXT NOT NULL, art TEXT NOT NULL, datum TEXT NOT NULL, betrag REAL,
    text TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS faelle (
    id TEXT PRIMARY KEY, schluessel TEXT UNIQUE NOT NULL, aktenzeichen TEXT NOT NULL, absender TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS ereignisse (
    id TEXT PRIMARY KEY, zeit TEXT NOT NULL, art TEXT NOT NULL, titel TEXT NOT NULL, text TEXT NOT NULL,
    dokument_id TEXT, daten TEXT NOT NULL DEFAULT '{}', geliefert TEXT
);
CREATE TABLE IF NOT EXISTS protokoll (zeit TEXT NOT NULL, wer TEXT NOT NULL, was TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS seiten (monat TEXT PRIMARY KEY, seiten INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS quellen (id TEXT PRIMARY KEY, daten TEXT NOT NULL, fehler TEXT NOT NULL DEFAULT '',
    letzter_abruf TEXT);
CREATE TABLE IF NOT EXISTS werte (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS eingang (quelle_id TEXT NOT NULL, eingang_id TEXT NOT NULL, version TEXT NOT NULL,
    PRIMARY KEY (quelle_id, eingang_id));
"""

DOCUMENT_FIELDS = (
    "art",
    "betreff",
    "absender",
    "datum",
    "aktenzeichen",
    "handlung",
    "betrag",
    "iban",
    "verwendungszweck",
    "ist_beleg",
    "vertraulich",
    "text",
    "status",
    "grund",
    "seiten",
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def case_key(file_number: str) -> str:
    """„St.-Nr. 123/456/78901“ and „123 456 78901“ are the same case."""
    key = re.sub(r"[^0-9a-z]", "", file_number.lower())
    return re.sub(r"^(stnr|az|aktenzeichen|steuernummer|kundennr|kundennummer)", "", key)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.originals = self.data_dir / "originale"
        self.originals.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "dms.sqlite3", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)

    def _all(self, sql: str, *args) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def _one(self, sql: str, *args) -> dict | None:
        rows = self._all(sql, *args)
        return rows[0] if rows else None

    def _run(self, sql: str, *args) -> None:
        with self.lock:
            self.db.execute(sql, args)

    # documents
    def by_sha(self, sha: str) -> dict | None:
        return self._one("SELECT * FROM dokumente WHERE sha256 = ?", sha)

    def document(self, doc_id: str) -> dict | None:
        return self._one("SELECT * FROM dokumente WHERE id = ?", doc_id)

    def add_document(self, *, sha: str, name: str, source: str, suffix: str, data: bytes, pages: int) -> dict:
        doc_id = uuid.uuid4().hex[:12]
        path = self.original_path(sha, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        t = now()
        self._run(
            "INSERT INTO dokumente (id, sha256, name, quelle, endung, empfangen, geaendert, seiten, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'neu')",
            doc_id,
            sha,
            name,
            source,
            suffix,
            t,
            t,
            pages,
        )
        return self.document(doc_id) or {}

    def original_path(self, sha: str, suffix: str) -> Path:
        return self.originals / sha[:2] / f"{sha}{suffix}"

    def original(self, doc: dict) -> bytes:
        return self.original_path(doc["sha256"], doc["endung"]).read_bytes()

    def update_document(self, doc_id: str, **fields) -> None:
        unknown = set(fields) - set(DOCUMENT_FIELDS) - {"fall_id"}
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE dokumente SET {sets}, geaendert = ? WHERE id = ?", *fields.values(), now(), doc_id)

    def documents(self, *, status: tuple[str, ...] = (), limit: int = 5000) -> list[dict]:
        if status:
            marks = ",".join("?" * len(status))
            return self._all(
                f"SELECT * FROM dokumente WHERE status IN ({marks}) ORDER BY empfangen, rowid LIMIT ?", *status, limit
            )
        return self._all("SELECT * FROM dokumente ORDER BY empfangen, rowid LIMIT ?", limit)

    def search(
        self,
        words: str,
        *,
        kind: str = "",
        since: str = "",
        until: str = "",
        confidential: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        sql, args = "SELECT * FROM dokumente WHERE status IN ('fertig', 'pruefen')", []
        if not confidential:
            sql += " AND vertraulich = 0"
        for word in words.split():
            sql += " AND (betreff LIKE ? OR absender LIKE ? OR aktenzeichen LIKE ? OR text LIKE ?)"
            args += [f"%{word}%"] * 4
        if kind:
            sql, args = sql + " AND art = ?", [*args, kind]
        if since:
            sql, args = sql + " AND COALESCE(NULLIF(datum, ''), substr(empfangen, 1, 10)) >= ?", [*args, since]
        if until:
            sql, args = sql + " AND COALESCE(NULLIF(datum, ''), substr(empfangen, 1, 10)) <= ?", [*args, until]
        return self._all(sql + " ORDER BY empfangen DESC LIMIT ?", *args, limit)

    # due dates
    def set_deadlines(self, doc_id: str, deadlines: list[dict]) -> None:
        with self.lock:
            self.db.execute("DELETE FROM fristen WHERE dokument_id = ?", (doc_id,))
            for i, f in enumerate(deadlines):
                self.db.execute(
                    "INSERT INTO fristen (id, dokument_id, art, datum, betrag, text) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"{doc_id}-{i}", doc_id, f["art"], f["datum"], f.get("betrag"), f.get("text", "")),
                )

    def deadlines(self, doc_id: str) -> list[dict]:
        return self._all("SELECT * FROM fristen WHERE dokument_id = ? ORDER BY datum", doc_id)

    def deadlines_between(self, since: str, until: str) -> list[dict]:
        return self._all(
            "SELECT f.*, d.absender, d.betreff, d.art AS dokument_art, d.vertraulich, d.aktenzeichen "
            "FROM fristen f JOIN dokumente d ON d.id = f.dokument_id "
            "WHERE f.datum >= ? AND f.datum <= ? ORDER BY f.datum",
            since,
            until,
        )

    # cases
    def case_for(self, file_number: str, sender: str) -> str | None:
        key = case_key(file_number)
        if len(key) < 4:
            return None
        found = self._one("SELECT id FROM faelle WHERE schluessel = ?", key)
        if found:
            return found["id"]
        case_id = uuid.uuid4().hex[:12]
        self._run(
            "INSERT INTO faelle (id, schluessel, aktenzeichen, absender) VALUES (?, ?, ?, ?)",
            case_id,
            key,
            file_number,
            sender,
        )
        return case_id

    def case_documents(self, case_id: str) -> list[dict]:
        return self._all("SELECT * FROM dokumente WHERE fall_id = ? ORDER BY datum, empfangen", case_id)

    # events
    def add_event(self, event_id: str, kind: str, title: str, text: str, doc_id: str | None, data: dict) -> None:
        self._run(
            "INSERT OR IGNORE INTO ereignisse (id, zeit, art, titel, text, dokument_id, daten) VALUES (?, ?, ?, ?, ?, ?, ?)",
            event_id,
            now(),
            kind,
            title,
            text,
            doc_id,
            json.dumps(data, ensure_ascii=False),
        )

    def events_for_cockpit(self, since: str, limit: int) -> list[dict]:
        """Not yet delivered first, then what is newer than `seit`. The cockpit takes at most 5 per fetch and moves `seit`
        on, so an undelivered event must come again until it was handed out once; ids it has seen it skips."""
        with self.lock:
            rows = self._all(
                "SELECT * FROM ereignisse WHERE geliefert IS NULL OR zeit > ? ORDER BY geliefert IS NOT NULL, "
                "zeit LIMIT ?",
                since or "9",
                limit,
            )
            t = now()
            for r in rows:
                if not r["geliefert"]:
                    self.db.execute("UPDATE ereignisse SET geliefert = ? WHERE id = ?", (t, r["id"]))
        return rows

    def events(self) -> list[dict]:
        return self._all("SELECT * FROM ereignisse ORDER BY zeit")

    # log
    def log(self, who: str, what: str) -> None:
        self._run("INSERT INTO protokoll (zeit, wer, was) VALUES (?, ?, ?)", now(), who, what)

    def log_between(self, since: str, until: str) -> list[dict]:
        return self._all(
            "SELECT zeit, wer, was FROM protokoll WHERE zeit >= ? AND zeit <= ? ORDER BY zeit", since, until
        )

    # pages
    def pages_used(self, month: str) -> int:
        row = self._one("SELECT seiten FROM seiten WHERE monat = ?", month)
        return int(row["seiten"]) if row else 0

    def add_pages(self, month: str, pages: int) -> None:
        self._run(
            "INSERT INTO seiten (monat, seiten) VALUES (?, ?) ON CONFLICT(monat) DO UPDATE SET seiten = seiten + ?",
            month,
            pages,
            pages,
        )

    # sources and values
    def set_sources(self, sources: list[dict]) -> None:
        with self.lock:
            keep = {s["id"] for s in sources}
            for row in self.db.execute("SELECT id FROM quellen").fetchall():
                if row["id"] not in keep:
                    self.db.execute("DELETE FROM quellen WHERE id = ?", (row["id"],))
            for s in sources:
                self.db.execute(
                    "INSERT INTO quellen (id, daten) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET daten = ?",
                    (s["id"], json.dumps(s), json.dumps(s)),
                )

    def sources(self) -> list[dict]:
        out = []
        for r in self._all("SELECT * FROM quellen ORDER BY id"):
            out.append(json.loads(r["daten"]) | {"_fehler": r["fehler"], "_letzter_abruf": r["letzter_abruf"]})
        return out

    def source_state(self, source_id: str, error: str) -> None:
        self._run("UPDATE quellen SET fehler = ?, letzter_abruf = ? WHERE id = ?", error, now(), source_id)

    def value(self, key: str, default: str = "") -> str:
        row = self._one("SELECT wert FROM werte WHERE schluessel = ?", key)
        return row["wert"] if row else default

    def set_value(self, key: str, value: str) -> None:
        self._run(
            "INSERT INTO werte (schluessel, wert) VALUES (?, ?) ON CONFLICT(schluessel) DO UPDATE SET wert = ?",
            key,
            value,
            value,
        )

    def seen(self, source_id: str, item_id: str) -> str | None:
        row = self._one("SELECT version FROM eingang WHERE quelle_id = ? AND eingang_id = ?", source_id, item_id)
        return row["version"] if row else None

    def mark_seen(self, source_id: str, item_id: str, version: str) -> None:
        self._run(
            "INSERT INTO eingang (quelle_id, eingang_id, version) VALUES (?, ?, ?) "
            "ON CONFLICT(quelle_id, eingang_id) DO UPDATE SET version = ?",
            source_id,
            item_id,
            version,
            version,
        )
