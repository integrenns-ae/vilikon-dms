"""Where post comes in: one adapter per kind of file store behind one interface.

- `list()`: what lies in the store's folder now, as `Item`s (id stable per file, version changes with the content);
- `fetch(item)`: its bytes;
- `mark_done(item)`: the document is in the DMS. Stores stay untouched unless the source says `verschieben: true`,
  then the file moves to the subfolder `erledigt/`.

A source is what the cockpit pushed in `PUT ki/quellen` (settings plus credentials from the vault):
`{"id", "art": "sftp|ftp|smb|gdrive|onedrive", "host", "port", "user", "passwort", "ordner", "verschieben"}`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.texte import t


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
        raise IntakeError(t("eingang.noch_nicht", art=source.get("art", "?")))


def open_adapter(source: dict) -> Adapter:
    from app.intake import sftp_ftp

    kind = source.get("art")
    if kind in ("sftp", "ftp"):
        return sftp_ftp.open_store(source)
    if kind in KINDS:
        return NotYet(source)  # type: ignore[return-value]
    raise IntakeError(t("eingang.art_unbekannt", art=kind or "?"))
