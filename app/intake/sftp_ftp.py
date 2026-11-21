"""SFTP and FTP(S): the scanner or NAS drops letters into one folder. Only that folder, no subfolders; only PDFs and
images up to 20 MB. Tests replace `CONNECT` with fakes that behave like paramiko's SFTPClient and ftplib.FTP; each
returns `(client, host_key)`.

An SFTP server's key is trusted on first use: the pipeline keeps the first key it saw per source and host, and when the
server shows another one the connection ends before the password is sent."""

from __future__ import annotations

import base64
import ftplib
import hashlib
import io
import posixpath
import socket
import stat

from app import ocr
from app.intake import IntakeError, Item
from app.texts import t

MAX_BYTES = 20 * 1024 * 1024
DONE_FOLDER = "done"
TIMEOUT_S = 30


def fingerprint(key) -> str:
    """As OpenSSH shows it: `ssh-ed25519 SHA256:…`."""
    digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    return f"{key.get_name()} SHA256:{digest}"


def _sftp_connect(source: dict):
    import paramiko

    sock = socket.create_connection((source["host"], int(source.get("port") or 22)), timeout=TIMEOUT_S)
    transport = paramiko.Transport(sock)
    try:
        transport.banner_timeout = TIMEOUT_S
        transport.start_client(timeout=TIMEOUT_S)
        seen = fingerprint(transport.get_remote_server_key())
        if source.get("host_key") and seen != source["host_key"]:
            raise IntakeError(t("intake.host_key_changed", host=source["host"]))
        transport.auth_password(source.get("user", ""), source.get("password", ""))
        return paramiko.SFTPClient.from_transport(transport), seen
    except BaseException:
        transport.close()
        raise


def _ftp_connect(source: dict):
    ftp = ftplib.FTP_TLS(timeout=TIMEOUT_S) if source.get("tls", True) else ftplib.FTP(timeout=TIMEOUT_S)
    ftp.connect(source["host"], int(source.get("port") or 21))
    ftp.login(source.get("user", ""), source.get("password", ""))
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()
    return ftp, ""


CONNECT = {"sftp": _sftp_connect, "ftp": _ftp_connect}


def open_store(source: dict):
    if not source.get("host"):
        raise IntakeError(t("intake.no_host"))
    name = str(source.get("protocol") or source["kind"]).upper()
    try:
        client, host_key = CONNECT[source["kind"]](source)
    except IntakeError:
        raise
    except Exception as e:  # network, login: the type is enough, never the password
        raise IntakeError(t("intake.no_connection", kind=name, error=type(e).__name__)) from e
    folder = "/" + str(source.get("folder") or "").strip("/")
    move = bool(source.get("move_done"))
    store = SftpStore(client, folder, move) if source["kind"] == "sftp" else FtpStore(client, folder, move)
    store.host_key = host_key
    return store


def _wanted(name: str, size: int) -> bool:
    return not name.startswith(".") and ocr.readable(name) and 0 < size <= MAX_BYTES


class SftpStore:
    host_key = ""

    def __init__(self, client, folder: str, move: bool) -> None:
        self.client, self.folder, self.move = client, folder, move

    def list(self) -> list[Item]:
        try:
            entries = self.client.listdir_attr(self.folder)
        except OSError as e:
            raise IntakeError(t("intake.folder_missing", folder=self.folder)) from e
        out = []
        for a in entries:
            if stat.S_ISREG(a.st_mode or 0) and _wanted(a.filename, a.st_size or 0):
                version = f"{int(a.st_mtime or 0)}-{a.st_size}"
                out.append(Item(posixpath.join(self.folder, a.filename), a.filename, version, int(a.st_size)))
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
    host_key = ""

    def __init__(self, client, folder: str, move: bool) -> None:
        self.client, self.folder, self.move = client, folder, move

    def list(self) -> list[Item]:
        try:
            entries = list(self.client.mlsd(self.folder, facts=["type", "size", "modify"]))
        except ftplib.all_errors as e:
            raise IntakeError(t("intake.folder_missing", folder=self.folder)) from e
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
