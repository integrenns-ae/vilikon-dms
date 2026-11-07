"""SFTP and FTP(S): the scanner or NAS drops letters into one folder. Only that folder, no subfolders; only PDFs and
images up to 20 MB. Tests replace `CONNECT` with fakes that behave like paramiko's SFTPClient and ftplib.FTP."""

from __future__ import annotations

import ftplib
import io
import posixpath
import stat

from app import ocr
from app.intake import IntakeError, Item
from app.texte import t

MAX_BYTES = 20 * 1024 * 1024
DONE_FOLDER = "erledigt"
TIMEOUT_S = 30


def _sftp_connect(source: dict):
    import paramiko

    transport = paramiko.Transport((source["host"], int(source.get("port") or 22)))
    transport.banner_timeout = TIMEOUT_S
    transport.connect(username=source.get("user", ""), password=source.get("passwort", ""))
    return paramiko.SFTPClient.from_transport(transport)


def _ftp_connect(source: dict):
    ftp = ftplib.FTP_TLS(timeout=TIMEOUT_S) if source.get("tls", True) else ftplib.FTP(timeout=TIMEOUT_S)
    ftp.connect(source["host"], int(source.get("port") or 21))
    ftp.login(source.get("user", ""), source.get("passwort", ""))
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    return ftp


CONNECT = {"sftp": _sftp_connect, "ftp": _ftp_connect}


def open_store(source: dict):
    if not source.get("host"):
        raise IntakeError(t("eingang.kein_host"))
    try:
        client = CONNECT[source["art"]](source)
    except IntakeError:
        raise
    except Exception as e:  # network, login: the type is enough, never the password
        raise IntakeError(t("eingang.verbindung", art=source["art"].upper(), fehler=type(e).__name__)) from e
    folder = "/" + str(source.get("ordner") or "").strip("/")
    move = bool(source.get("verschieben"))
    return SftpStore(client, folder, move) if source["art"] == "sftp" else FtpStore(client, folder, move)


def _wanted(name: str, size: int) -> bool:
    return not name.startswith(".") and ocr.readable(name) and 0 < size <= MAX_BYTES


class SftpStore:
    def __init__(self, client, folder: str, move: bool) -> None:
        self.client, self.folder, self.move = client, folder, move

    def list(self) -> list[Item]:
        try:
            entries = self.client.listdir_attr(self.folder)
        except OSError as e:
            raise IntakeError(t("eingang.ordner_fehlt", ordner=self.folder)) from e
        out = []
        for a in entries:
            if stat.S_ISREG(a.st_mode or 0) and _wanted(a.filename, a.st_size or 0):
                out.append(
                    Item(
                        posixpath.join(self.folder, a.filename),
                        a.filename,
                        f"{int(a.st_mtime or 0)}-{a.st_size}",
                        int(a.st_size),
                    )
                )
        return sorted(out, key=lambda i: i.id)

    def fetch(self, item: Item) -> bytes:
        with self.client.open(item.id, "rb") as f:
            return f.read()

    def mark_done(self, item: Item) -> None:
        if not self.move:
            return
        done = posixpath.join(self.folder, DONE_FOLDER)
        try:
            self.client.stat(done)
        except OSError:
            self.client.mkdir(done)
        self.client.rename(item.id, posixpath.join(done, item.name))

    def close(self) -> None:
        self.client.close()


class FtpStore:
    def __init__(self, client, folder: str, move: bool) -> None:
        self.client, self.folder, self.move = client, folder, move

    def list(self) -> list[Item]:
        try:
            entries = list(self.client.mlsd(self.folder, facts=["type", "size", "modify"]))
        except ftplib.all_errors as e:
            raise IntakeError(t("eingang.ordner_fehlt", ordner=self.folder)) from e
        out = []
        for name, facts in entries:
            size = int(facts.get("size") or 0)
            if facts.get("type") == "file" and _wanted(name, size):
                out.append(Item(posixpath.join(self.folder, name), name, f"{facts.get('modify', '')}-{size}", size))
        return sorted(out, key=lambda i: i.id)

    def fetch(self, item: Item) -> bytes:
        buf = io.BytesIO()
        self.client.retrbinary(f"RETR {item.id}", buf.write)
        return buf.getvalue()

    def mark_done(self, item: Item) -> None:
        if not self.move:
            return
        done = posixpath.join(self.folder, DONE_FOLDER)
        try:
            self.client.mkd(done)
        except ftplib.error_perm:
            pass  # already there
        self.client.rename(item.id, posixpath.join(done, item.name))

    def close(self) -> None:
        try:
            self.client.quit()
        except ftplib.all_errors:
            self.client.close()
