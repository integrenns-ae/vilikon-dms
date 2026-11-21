"""What the first live install showed: a folder full of old scans must not flood the owner, a day already past is no
new due date, and a receipt goes to the bookkeeping only when the cockpit can make a card of it."""

import sqlite3

import pytest
from conftest import letter, recorded, with_annotation

from app import pipeline
from app.store import Store

# Invented letters, dated against the tests' day 2026-11-21 (conftest.TODAY).
OLD_INVOICE = {
    "subject": "Rechnung Nr. RE-2026-0412",
    "date": "2026-08-03",
    "file_number": "RE-2026-0412",
    "payment_reference": "RE-2026-0412",
    "amount": 238.0,
    "due_dates": [{"kind": "payment", "date": "2026-08-17", "amount": 238.0, "certain": True, "text": "zahlbar bis"}],
}
OLD_COURT = {
    "kind": "court",
    "subject": "Ladung zum Termin",
    "sender": "Amtsgericht Musterstadt",
    "date": "2026-09-01",
    "file_number": "12 C 345/26",
    "action": "deadline",
    "amount": None,
    "iban": "",
    "payment_reference": "",
    "is_receipt": False,
    "due_dates": [{"kind": "court", "date": "2027-01-15", "amount": None, "certain": True, "text": "Termin"}],
}
OLD_UNCLEAR = {
    "kind": "letter",
    "subject": "Ihre Anfrage",
    "sender": "Erika Muster",
    "date": "2026-07-10",
    "file_number": "",
    "action": "reply",
    "amount": None,
    "iban": "",
    "payment_reference": "",
    "is_receipt": False,
    "due_dates": [{"kind": "reply", "date": "", "amount": None, "certain": False, "text": "bald"}],
}
OLD_DUE_DATE = {
    "kind": "notice",
    "subject": "Vorauszahlung Gewerbesteuer",
    "sender": "Stadt Musterstadt",
    "date": "2026-09-15",
    "file_number": "GewSt-4711",
    "action": "none",
    "amount": None,
    "iban": "",
    "payment_reference": "",
    "is_receipt": False,
    "due_dates": [{"kind": "tax", "date": "2026-12-10", "amount": 150.0, "certain": True, "text": "fällig am"}],
}


def _put(scanner, mistral, name: str, seed: int, **changes) -> None:
    (scanner.folder / name).write_bytes(mistral.answer(letter(seed), with_annotation(recorded("invoice"), **changes)))


def _only(scanner, mistral, name: str, **changes) -> None:
    """The folder holds just this one letter."""
    for f in scanner.folder.iterdir():
        if f.is_file():
            f.unlink()
    _put(scanner, mistral, name, 90, **changes)


def _by_subject(store) -> dict[str, dict]:
    return {d["subject"]: d for d in store.documents()}


def test_the_first_fetch_files_old_letters_without_tasks(cockpit, scanner, mistral, store, fetch):
    for i, old in enumerate((OLD_INVOICE, OLD_COURT, OLD_UNCLEAR, OLD_DUE_DATE)):
        _put(scanner, mistral, f"alt_{i:03}.pdf", 80 + i, **old)
    cockpit.sync_now()

    docs = _by_subject(store)
    assert len(docs) == 7
    old = [docs[x["subject"]] for x in (OLD_INVOICE, OLD_COURT, OLD_UNCLEAR, OLD_DUE_DATE)]
    assert {(d["status"], d["reason"], d["backlog"]) for d in old} == {("done", "archive", 1)}
    assert store.documents(status=("review",)) == []
    # Only the three recent letters speak up, exactly as without the old ones.
    events = cockpit.poll_events() + cockpit.poll_events()
    assert sorted(e["art"] for e in events) == ["pay", "pay", "receipt"]
    assert {e["data"]["document_id"] for e in events}.isdisjoint(d["id"] for d in old)

    # Filed: found, in the company memory, and their dates still ahead are in the morning briefing.
    found = cockpit.get("ki/documents", query="RE-2026-0412").json()["documents"]
    assert [f["status"] for f in found] == ["done"] and found[0]["reason"].startswith("Älterer Brief")
    assert any(f["meta"]["file_number"] == "GewSt-4711" for f in cockpit.sync_knowledge().values())
    due = cockpit.get("ki/due_dates", **{"from": "2026-11-21", "to": "2027-01-31"}).json()["due_dates"]
    assert ("2026-12-10", "tax") in [(d["date"], d["kind"]) for d in due]
    assert ("2027-01-15", "court") in [(d["date"], d["kind"]) for d in due]

    # The first fetch is over: an old letter scanned now is meant to be seen.
    _put(scanner, mistral, "spaet.pdf", 89, **OLD_INVOICE | {"subject": "Rechnung Nr. RE-2026-0413"})
    fetch()
    late = _by_subject(store)["Rechnung Nr. RE-2026-0413"]
    assert (late["status"], late["reason"], late["backlog"]) == ("done", "", 0)
    assert sorted(e["art"] for e in cockpit.poll_events()) == ["pay", "receipt"]


def test_a_first_fetch_over_several_passes_stays_the_first(cockpit, scanner, mistral, store, fetch, monkeypatch):
    monkeypatch.setattr(pipeline, "ITEMS_PER_PASS", 2)
    _put(scanner, mistral, "zz_alt.pdf", 81, **OLD_INVOICE)  # listed last: fetched in the second pass
    assert fetch()["new"] == 2
    assert fetch()["new"] == 2
    old = _by_subject(store)[OLD_INVOICE["subject"]]
    assert (old["reason"], old["backlog"]) == ("archive", 1)
    _put(scanner, mistral, "zz_neu.pdf", 82, **OLD_INVOICE | {"subject": "Rechnung Nr. RE-2026-0414"})
    assert fetch()["new"] == 1
    assert _by_subject(store)["Rechnung Nr. RE-2026-0414"]["reason"] == ""


def test_another_folder_has_a_first_fetch_of_its_own(cockpit, scanner, mistral, store, fetch, vault):
    cockpit.sync_now()
    (scanner.root / "archiv").mkdir()
    (scanner.root / "archiv" / "alt.pdf").write_bytes(
        mistral.answer(letter(83), with_annotation(recorded("invoice"), **OLD_INVOICE))
    )
    vault(SCANNER_FOLDER="/archiv")
    fetch()
    assert _by_subject(store)[OLD_INVOICE["subject"]]["reason"] == "archive"


@pytest.mark.parametrize(("days", "reason"), [("0", ""), ("200", ""), ("60", "archive")])
def test_how_old_is_old_is_a_setting(cockpit, scanner, mistral, store, vault, days, reason):
    vault(DMS_ARCHIVE_DAYS=days)
    _only(scanner, mistral, "alt.pdf", **OLD_INVOICE)  # 110 days before it comes in
    cockpit.sync_now()
    assert store.documents()[0]["reason"] == reason
    assert sorted(e["art"] for e in cockpit.poll_events()) == ([] if reason else ["pay", "receipt"])


def test_old_means_more_than_the_days_before_it_came_in(env):
    doc = {"backlog": 1, "received_at": "2026-11-21T08:00:00+00:00"}
    assert pipeline.archived(doc, "2026-10-21") is True  # 31 days
    assert pipeline.archived(doc, "2026-10-22") is False  # 30 days
    assert pipeline.archived(doc, "") is False  # no date read: not clearly old
    assert pipeline.archived(doc | {"backlog": 0}, "2025-01-01") is False  # uploads and later scans


def test_a_day_already_past_is_no_new_due_date(cockpit, scanner, mistral, store):
    days = [
        {"kind": "tax", "date": day, "amount": None, "certain": True, "text": ""}
        for day in ("2026-11-10", "2026-11-21", "2026-12-10")
    ]
    _only(scanner, mistral, "bescheid.pdf", **OLD_DUE_DATE | {"date": "2026-11-05", "due_dates": days})
    cockpit.sync_now()
    doc = store.documents()[0]
    assert [d["date"] for d in store.due_dates(doc["id"])] == ["2026-11-10", "2026-11-21", "2026-12-10"]
    events = cockpit.poll_events()
    assert sorted((e["art"], e["data"]["due_date"]["date"]) for e in events) == [
        ("new_due_date", "2026-11-21"),
        ("new_due_date", "2026-12-10"),
    ]


@pytest.mark.parametrize(
    ("changes", "reason", "words"),
    [
        ({"amount": None}, "receipt_no_amount", "Beleg: Betrag nicht erkannt"),
        ({"amount": 0}, "receipt_no_amount", "Beleg: Betrag nicht erkannt"),
        ({"sender": " "}, "receipt_no_sender", "Beleg: Absender nicht erkannt"),
        ({"date": "03.08.2026"}, "receipt_no_date", "Beleg: Datum nicht erkannt"),
    ],
)
def test_a_receipt_without_amount_sender_or_date_goes_on_review(
    cockpit, scanner, mistral, store, changes, reason, words
):
    _only(scanner, mistral, "rechnung.pdf", **changes)
    cockpit.sync_now()
    doc = store.documents()[0]
    assert (doc["status"], doc["reason"], doc["is_receipt"]) == ("review", reason, 1)
    (event,) = cockpit.poll_events()
    assert event["art"] == "review" and event["data"]["reason"] == reason
    assert event["text"].startswith(words) and "selbst erfassen" in event["text"]
    assert cockpit.get("ki/karten/mail").json()["ton"] == "kritisch"


def test_a_receipt_on_review_for_something_else_says_both(cockpit, scanner, mistral, store):
    unclear = [{"kind": "payment", "date": "", "amount": None, "certain": False, "text": "binnen 14 Tagen"}]
    _only(scanner, mistral, "rechnung.pdf", amount=None, due_dates=unclear)
    cockpit.sync_now()
    assert store.documents()[0]["reason"] == "deadline_unclear"
    (event,) = cockpit.poll_events()
    assert event["art"] == "review"
    assert "Eine Frist ist nicht eindeutig" in event["text"] and "Beleg: Betrag nicht erkannt" in event["text"]


def test_a_database_of_0_2_1_gets_the_new_columns(tmp_path):
    db = sqlite3.connect(tmp_path / "dms.sqlite3")
    db.executescript(
        "CREATE TABLE documents (id TEXT PRIMARY KEY, sha256 TEXT UNIQUE NOT NULL, name TEXT NOT NULL, "
        "source TEXT NOT NULL, suffix TEXT NOT NULL, received_at TEXT NOT NULL, updated_at TEXT NOT NULL, "
        "pages INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', "
        "kind TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', sender TEXT NOT NULL DEFAULT '', "
        "date TEXT NOT NULL DEFAULT '', file_number TEXT NOT NULL DEFAULT '', action TEXT NOT NULL DEFAULT '', "
        "amount REAL, iban TEXT NOT NULL DEFAULT '', payment_reference TEXT NOT NULL DEFAULT '', "
        "is_receipt INTEGER NOT NULL DEFAULT 0, confidential INTEGER NOT NULL DEFAULT 0, "
        "text TEXT NOT NULL DEFAULT '', case_id TEXT);"
        "CREATE TABLE source_state (id TEXT PRIMARY KEY, error TEXT NOT NULL DEFAULT '', last_fetch TEXT, "
        "host_key_for TEXT NOT NULL DEFAULT '', host_key TEXT NOT NULL DEFAULT '', "
        "host_key_new TEXT NOT NULL DEFAULT '');"
        "INSERT INTO documents (id, sha256, name, source, suffix, received_at, updated_at, status) "
        "VALUES ('a1', 'f00', 'scan_001.pdf', 'scanner', '.pdf', '2026-11-20', '2026-11-20', 'done');"
        "INSERT INTO source_state (id, last_fetch) VALUES ('scanner', '2026-11-20T08:00:00+00:00');"
    )
    db.close()
    store = Store(tmp_path)
    assert store.document("a1")["backlog"] == 0
    assert store.source_states()["scanner"]["caught_up"] == ""
