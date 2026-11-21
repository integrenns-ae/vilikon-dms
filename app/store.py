"""SQLite under $DATA_DIR: documents with what was read from them, due dates, cases by file number, events for the
cockpit, the log, page counts, the state of each file store. Originals lie beside it in `originals/`. One connection,
one lock: the DMS handles a handful of letters a day.

Nothing secret lies here: the file stores and the OCR key come from the environment (app/config.py)."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, name TEXT NOT NULL, source TEXT NOT NULL, suffix TEXT NOT NULL,
    received_at TEXT NOT NULL, updated_at TEXT NOT NULL, pages INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', sender TEXT NOT NULL DEFAULT '',
    date TEXT NOT NULL DEFAULT '', file_number TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '',
    amount REAL, iban TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '',
    is_receipt INTEGER NOT NULL DEFAULT 0, confidential INTEGER NOT NULL DEFAULT 0,
    text TEXT NOT NULL DEFAULT '', case_id TEXT, backlog INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS due_dates (
    id TEXT PRIMARY KEY, document_id TEXT NOT NULL, kind TEXT NOT NULL, date TEXT NOT NULL, amount REAL,
    text TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY, key TEXT UNIQUE NOT NULL, file_number TEXT NOT NULL, sender TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY, time TEXT NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
    document_id TEXT, data TEXT NOT NULL DEFAULT '{}', delivered_at TEXT
);
CREATE TABLE IF NOT EXISTS log (time TEXT NOT NULL, who TEXT NOT NULL, what TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pages (month TEXT PRIMARY KEY, pages INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS source_state (id TEXT PRIMARY KEY, error TEXT NOT NULL DEFAULT '', last_fetch TEXT,
    host_key_for TEXT NOT NULL DEFAULT '', host_key TEXT NOT NULL DEFAULT '', host_key_new TEXT NOT NULL DEFAULT '',
    caught_up TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS intake_seen (source_id TEXT NOT NULL, item_id TEXT NOT NULL, version TEXT NOT NULL,
    PRIMARY KEY (source_id, item_id));
"""
# Columns added after 0.2.1, for a database an older version made: table → [(column, definition)].
ADDED = {
    "documents": [("backlog", "INTEGER NOT NULL DEFAULT 0")],
    "source_state": [("caught_up", "TEXT NOT NULL DEFAULT ''")],
}

DOCUMENT_FIELDS = (
    "kind",
    "subject",
    "sender",
    "date",
    "file_number",
    "action",
    "amount",
    "iban",
    "payment_reference",
    "is_receipt",
    "confidential",
    "text",
    "status",
    "reason",
    "pages",
    "case_id",
)


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def today() -> date:
    """The day by the same clock as `now` (tests set it there)."""
    return date.fromisoformat(now()[:10])


def case_key(file_number: str) -> str:
    """„St.-Nr. 123/456/78901“ and „123 456 78901“ are the same case."""
    key = re.sub(r"[^0-9a-z]", "", file_number.lower())
    return re.sub(r"^(stnr|az|aktenzeichen|steuernummer|kundennr|kundennummer)", "", key)


class Store:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.originals = self.data_dir / "originals"
        self.originals.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.data_dir / "dms.sqlite3", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)
            self._add_columns()
            self._forget_pushed_secrets()

    def _add_columns(self) -> None:
        for table, columns in ADDED.items():
            have = {r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns:
                if name not in have:
                    self.db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def _forget_pushed_secrets(self) -> None:
        """Up to 0.1 the cockpit pushed the file stores with their passwords (`PUT ki/sources`, table `sources`) and the
        customer's Mistral key (table `settings`) into this database. Both come from the environment now: overwrite
        what is left of them, free pages and the write-ahead log included."""
        sql = "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('sources', 'settings')"
        if not self.db.execute(sql).fetchall():
            return
        self.db.execute("PRAGMA secure_delete = ON")
        self.db.execute("DROP TABLE IF EXISTS sources")
        self.db.execute("DROP TABLE IF EXISTS settings")
        self.db.execute("VACUUM")
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("PRAGMA secure_delete = OFF")

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
        return self._one("SELECT * FROM documents WHERE sha256 = ?", sha)

    def document(self, doc_id: str) -> dict | None:
        return self._one("SELECT * FROM documents WHERE id = ?", doc_id)

    def add_document(
        self, *, sha: str, name: str, source: str, suffix: str, data: bytes, pages: int, backlog: bool = False
    ) -> dict:
        """`backlog`: it lay in its file store before the DMS had fetched everything there once (app/pipeline.py)."""
        doc_id = uuid.uuid4().hex[:12]
        path = self.original_path(sha, suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        t = now()
        self._run(
            "INSERT INTO documents (id, sha256, name, source, suffix, received_at, updated_at, pages, status, backlog) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)",
            doc_id,
            sha,
            name,
            source,
            suffix,
            t,
            t,
            pages,
            int(backlog),
        )
        return self.document(doc_id) or {}

    def original_path(self, sha: str, suffix: str) -> Path:
        return self.originals / sha[:2] / f"{sha}{suffix}"

    def original(self, doc: dict) -> bytes:
        return self.original_path(doc["sha256"], doc["suffix"]).read_bytes()

    def update_document(self, doc_id: str, **fields) -> None:
        unknown = set(fields) - set(DOCUMENT_FIELDS)
        if unknown:
            raise ValueError(f"unknown fields: {sorted(unknown)}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._run(f"UPDATE documents SET {sets}, updated_at = ? WHERE id = ?", *fields.values(), now(), doc_id)

    def documents(self, *, status: tuple[str, ...] = (), limit: int = 5000) -> list[dict]:
        if status:
            marks = ",".join("?" * len(status))
            sql = f"SELECT * FROM documents WHERE status IN ({marks}) ORDER BY received_at, rowid LIMIT ?"
            return self._all(sql, *status, limit)
        return self._all("SELECT * FROM documents ORDER BY received_at, rowid LIMIT ?", limit)

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
        sql, args = "SELECT * FROM documents WHERE status IN ('done', 'review')", []
        if not confidential:
            sql += " AND confidential = 0"
        for word in words.split():
            sql += " AND (subject LIKE ? OR sender LIKE ? OR file_number LIKE ? OR text LIKE ?)"
            args += [f"%{word}%"] * 4
        day = "COALESCE(NULLIF(date, ''), substr(received_at, 1, 10))"
        if kind:
            sql, args = sql + " AND kind = ?", [*args, kind]
        if since:
            sql, args = sql + f" AND {day} >= ?", [*args, since]
        if until:
            sql, args = sql + f" AND {day} <= ?", [*args, until]
        return self._all(sql + " ORDER BY received_at DESC LIMIT ?", *args, limit)

    # due dates
    def set_due_dates(self, doc_id: str, due_dates: list[dict]) -> None:
        with self.lock:
            self.db.execute("DELETE FROM due_dates WHERE document_id = ?", (doc_id,))
            for i, d in enumerate(due_dates):
                self.db.execute(
                    "INSERT INTO due_dates (id, document_id, kind, date, amount, text) VALUES (?, ?, ?, ?, ?, ?)",
                    (f"{doc_id}-{i}", doc_id, d["kind"], d["date"], d.get("amount"), d.get("text", "")),
                )

    def due_dates(self, doc_id: str) -> list[dict]:
        return self._all("SELECT * FROM due_dates WHERE document_id = ? ORDER BY date", doc_id)

    def due_dates_between(self, since: str, until: str) -> list[dict]:
        return self._all(
            "SELECT u.*, d.sender, d.subject, d.kind AS document_kind, d.confidential, d.file_number "
            "FROM due_dates u JOIN documents d ON d.id = u.document_id "
            "WHERE u.date >= ? AND u.date <= ? ORDER BY u.date",
            since,
            until,
        )

    # cases
    def case_for(self, file_number: str, sender: str) -> str | None:
        key = case_key(file_number)
        if len(key) < 4:
            return None
        found = self._one("SELECT id FROM cases WHERE key = ?", key)
        if found:
            return found["id"]
        case_id = uuid.uuid4().hex[:12]
        self._run(
            "INSERT INTO cases (id, key, file_number, sender) VALUES (?, ?, ?, ?)", case_id, key, file_number, sender
        )
        return case_id

    def case_documents(self, case_id: str) -> list[dict]:
        return self._all("SELECT * FROM documents WHERE case_id = ? ORDER BY date, received_at", case_id)

    # events
    def add_event(self, event_id: str, kind: str, title: str, text: str, doc_id: str | None, data: dict) -> None:
        self._run(
            "INSERT OR IGNORE INTO events (id, time, kind, title, text, document_id, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
            event_id,
            now(),
            kind,
            title,
            text,
            doc_id,
            json.dumps(data, ensure_ascii=False),
        )

    def events_for_cockpit(self, since: str, limit: int) -> list[dict]:
        """Not yet delivered first, then what is newer than `since`. The cockpit takes at most 5 per fetch and moves
        `seit` on, so an undelivered event must come again until it was handed out once; ids it has seen it skips."""
        with self.lock:
            rows = self._all(
                "SELECT * FROM events WHERE delivered_at IS NULL OR time > ? "
                "ORDER BY delivered_at IS NOT NULL, time LIMIT ?",
                since or "9",
                limit,
            )
            t = now()
            for r in rows:
                if not r["delivered_at"]:
                    self.db.execute("UPDATE events SET delivered_at = ? WHERE id = ?", (t, r["id"]))
        return rows

    # log
    def log(self, who: str, what: str) -> None:
        self._run("INSERT INTO log (time, who, what) VALUES (?, ?, ?)", now(), who, what)

    def log_between(self, since: str, until: str) -> list[dict]:
        return self._all("SELECT time, who, what FROM log WHERE time >= ? AND time <= ? ORDER BY time", since, until)

    # pages
    def pages_used(self, month: str) -> int:
        row = self._one("SELECT pages FROM pages WHERE month = ?", month)
        return int(row["pages"]) if row else 0

    def add_pages(self, month: str, pages: int) -> None:
        self._run(
            "INSERT INTO pages (month, pages) VALUES (?, ?) ON CONFLICT(month) DO UPDATE SET pages = pages + ?",
            month,
            pages,
            pages,
        )

    # file stores: only what the DMS found out about them; their settings and passwords come from the environment
    def source_states(self) -> dict[str, dict]:
        return {r["id"]: r for r in self._all("SELECT * FROM source_state")}

    def source_state(self, source_id: str, error: str, *, fetched: bool = True) -> None:
        """After a pass (`fetched`) or a check: the error, "" when it worked."""
        self._run("INSERT OR IGNORE INTO source_state (id) VALUES (?)", source_id)
        if fetched:
            self._run("UPDATE source_state SET error = ?, last_fetch = ? WHERE id = ?", error, now(), source_id)
        else:
            self._run("UPDATE source_state SET error = ? WHERE id = ?", error, source_id)

    def set_host_key(self, source_id: str, where: str, key: str) -> None:
        """The SFTP server's key, trusted on first use, for this host and port."""
        self._run("INSERT OR IGNORE INTO source_state (id) VALUES (?)", source_id)
        self._run(
            "UPDATE source_state SET host_key_for = ?, host_key = ?, host_key_new = '' WHERE id = ?",
            where,
            key,
            source_id,
        )

    def set_caught_up(self, source_id: str, where: str) -> None:
        """Everything that lay in this store's folder has come in once: its first fetch is over, for this place."""
        self._run("INSERT OR IGNORE INTO source_state (id) VALUES (?)", source_id)
        self._run("UPDATE source_state SET caught_up = ? WHERE id = ?", where, source_id)

    def set_new_host_key(self, source_id: str, key: str) -> None:
        """The other key the server showed: not trusted until the owner accepts it."""
        self._run("UPDATE source_state SET host_key_new = ? WHERE id = ?", key, source_id)

    def accept_host_key(self, source_id: str) -> bool:
        with self.lock:
            row = self._one("SELECT host_key_new FROM source_state WHERE id = ?", source_id)
            if not row or not row["host_key_new"]:
                return False
            self._run(
                "UPDATE source_state SET host_key = host_key_new, host_key_new = '', error = '' WHERE id = ?", source_id
            )
            return True

    def seen(self, source_id: str, item_id: str) -> str | None:
        row = self._one("SELECT version FROM intake_seen WHERE source_id = ? AND item_id = ?", source_id, item_id)
        return row["version"] if row else None

    def mark_seen(self, source_id: str, item_id: str, version: str) -> None:
        self._run(
            "INSERT INTO intake_seen (source_id, item_id, version) VALUES (?, ?, ?) "
            "ON CONFLICT(source_id, item_id) DO UPDATE SET version = ?",
            source_id,
            item_id,
            version,
            version,
        )
