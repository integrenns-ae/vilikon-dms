"""The file stores, from the environment. Every vault entry of type `filestore` the owner released for the DMS
(the credential `SCANNER`, more as `SCANNER2` …) arrives as

    SCANNER_ART=filestore  SCANNER_PROTOCOL=sftp|ftps|ftp  SCANNER_HOST  SCANNER_PORT  SCANNER_USER  SCANNER_FOLDER
    SCANNER_MOVE_DONE  SCANNER_PASSWORT

and becomes a source with `id` = the name in lower case. Read on every pass; nothing of it is stored."""

from __future__ import annotations

from collections.abc import Mapping

from app.config import TRUE

FILESTORE = "filestore"
SUFFIX = "_ART"
PROTOCOLS = {"sftp": ("sftp", True), "ftps": ("ftp", True), "ftp": ("ftp", False)}  # protocol → kind, tls


def sources_from_env(environ: Mapping[str, str]) -> list[dict]:
    out = []
    for key, value in environ.items():
        prefix = key.removesuffix(SUFFIX)
        if not prefix or prefix == key or value.strip().lower() != FILESTORE:
            continue

        def get(name: str, prefix: str = prefix) -> str:
            return environ.get(f"{prefix}_{name}", "").strip()

        protocol = get("PROTOCOL").lower()
        kind, tls = PROTOCOLS.get(protocol, (protocol, True))  # smb, gdrive …: the adapter says "not yet"
        port = get("PORT")
        out.append(
            {
                "id": prefix.lower(),
                "kind": kind,
                "protocol": protocol,
                "tls": tls,
                "host": get("HOST"),
                "port": int(port) if port.isdigit() else None,
                "user": get("USER"),
                "password": environ.get(f"{prefix}_PASSWORT", ""),
                "folder": get("FOLDER"),
                "move_done": get("MOVE_DONE").lower() in TRUE,
            }
        )
    return sorted(out, key=lambda s: s["id"])
