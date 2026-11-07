"""Where post comes in: one adapter per kind of file store behind one interface.

- `list()`: what lies in the store's folder now, as `Item`s (id stable per file, version changes with the content);
- `fetch(item)`: its bytes;
- `mark_done(item)`: the document is in the DMS. Stores stay untouched unless the source says `move_done: true`,
  then the file moves to the subfolder `done/`.

A source is what the cockpit pushed in `PUT ki/sources` (settings plus credentials from the vault):
`{"id", "kind": "sftp|ftp|smb|gdrive|onedrive", "host", "port", "user", "password", "folder", "move_done", "tls",
"active"}`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.texts import t


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    version: str
    size: int


class IntakeError(Exception):
    """Said in plain words: it ends on the source's status in the cockpit."""


class Adapter(Protocol):
    def list(self) -> list[Item]: ...
    def fetch(self, item: Item) -> bytes: ...
    def mark_done(self, item: Item) -> None: ...
    def close(self) -> None: ...


KINDS = ("sftp", "ftp", "smb", "gdrive", "onedrive")


class NotYet:
    """SMB, Google Drive and OneDrive come in a later phase."""

    def __init__(self, source: dict) -> None:
        raise IntakeError(t("intake.not_yet", kind=source.get("kind", "?")))


def open_adapter(source: dict) -> Adapter:
    from app.intake import sftp_ftp

    kind = source.get("kind")
    if kind in ("sftp", "ftp"):
        return sftp_ftp.open_store(source)
    if kind in KINDS:
        return NotYet(source)  # type: ignore[return-value]
    raise IntakeError(t("intake.unknown_kind", kind=kind or "?"))
