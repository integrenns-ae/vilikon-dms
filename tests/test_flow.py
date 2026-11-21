"""Three invented letters from the scanner's SFTP folder, through the DMS, as the cockpit sees them."""

from conftest import letter, recorded, with_annotation


def _setup(cockpit):
    counts = cockpit.sync_now()
    assert "secret-sftp" not in str(counts)
    return counts


def test_letters_are_read_filed_and_announced(cockpit, scanner, mistral, store):
    counts = _setup(cockpit)
    assert counts["new"] == 3 and counts["read"] == 3 and counts["errors"] == 0
    assert counts["sources"][0]["error"] == ""
    assert scanner.clients[-1].closed

    sent = mistral.requests[0]
    assert sent["model"] == "mistral-ocr-latest" and sent["_auth"] == "Bearer operator-key"
    assert sent["document_annotation_format"]["json_schema"]["strict"] is True

    docs = {d["kind"]: d for d in store.documents()}
    assert set(docs) == {"invoice", "notice", "advertising"}
    assert all(d["status"] == "done" for d in docs.values())
    invoice, notice = docs["invoice"], docs["notice"]
    assert invoice["iban"] == "DE89370400440532013000" and invoice["amount"] == 1190.0 and invoice["is_receipt"] == 1
    assert notice["confidential"] == 1 and notice["pages"] == 2
    assert [d["date"] for d in store.due_dates(notice["id"])] == ["2026-11-16", "2026-12-07", "2027-03-10"]

    events = cockpit.poll_events()
    assert sorted(e["art"] for e in events) == ["pay", "pay", "receipt"]  # advertising: nothing to do
    pay = next(e for e in events if e["art"] == "pay" and e["data"]["document_id"] == invoice["id"])
    assert pay["titel"] == "Zahlen: Musterfirma GmbH – Rechnung Nr. RE-2026-0815"
    assert "1190.00 EUR" in pay["text"] and "2026-11-20" in pay["text"]
    assert pay["data"]["iban"] == "DE89370400440532013000" and pay["data"]["owner_only"] is False
    assert cockpit.poll_events() == []

    log = cockpit.get("ki/protokoll").json()
    assert any("Gelesen: Finanzamt Musterstadt" in p["was"] for p in log)


def test_second_pass_and_same_letter_twice_are_not_read_again(cockpit, scanner, mistral, store):
    _setup(cockpit)
    calls = len(mistral.requests)
    again = cockpit.sync_now()
    assert again["new"] == 0 and again["duplicate"] == 0 and len(mistral.requests) == calls
    # the same scan under another name (scanned twice, or photographed as well)
    (scanner.folder / "scan_004.pdf").write_bytes((scanner.folder / "scan_001.pdf").read_bytes())
    again = cockpit.sync_now()
    assert again["duplicate"] == 1 and len(store.documents()) == 3 and len(mistral.requests) == calls


def test_knowledge_files_for_the_company_memory(cockpit, scanner):
    _setup(cockpit)
    memory = cockpit.sync_knowledge()
    assert len(memory) == 3
    notice = next(f for f in memory.values() if f["meta"]["kind"] == "notice")
    assert notice["sensibel"] is True
    assert notice["pfad"] == "Post/2026/2026-11-04 Finanzamt Musterstadt – Bescheid für 2025 über Einkommensteuer.md"
    assert notice["meta"]["due_dates"] == ["2026-11-16", "2026-12-07", "2027-03-10"]
    assert "- Aktenzeichen: St.-Nr. 123/456/78901" in notice["text"] and "Rechtsbehelfsbelehrung" in notice["text"]
    assert sum(1 for f in memory.values() if f["sensibel"]) == 1
    versions = {k: v["version"] for k, v in memory.items()}
    assert {k: v["version"] for k, v in cockpit.sync_knowledge().items()} == versions


def test_functions_for_employees(cockpit, scanner, store):
    _setup(cockpit)
    found = cockpit.get("ki/documents", who="anna", query="Musterfirma").json()["documents"]
    assert [d["kind"] for d in found] == ["invoice"]
    # the tax notice is confidential: not without the right, found with it
    assert cockpit.get("ki/documents", query="Finanzamt").json()["documents"] == []
    secret = cockpit.get("ki/confidential/documents", query="Finanzamt").json()["documents"]
    assert len(secret) == 1
    assert cockpit.get(f"ki/documents/{secret[0]['id']}").status_code == 404
    full = cockpit.get(f"ki/confidential/documents/{secret[0]['id']}").json()
    assert full["amount"] == 842.0 and len(full["due_dates"]) == 3

    due = cockpit.get("ki/due_dates", **{"from": "2026-11-01", "to": "2026-12-31"}).json()["due_dates"]
    assert [(d["date"], d["kind"]) for d in due] == [
        ("2026-11-16", "payment"),
        ("2026-11-20", "payment"),
        ("2026-12-07", "objection"),
    ]
    assert due[0]["confidential"] is True and due[0]["sender"] == "Vertraulicher Brief" and due[0]["amount"] is None
    assert due[1]["sender"] == "Musterfirma GmbH" and due[1]["amount"] == 1190.0

    invoice = found[0]["id"]
    receipt = cockpit.get(f"ki/receipts/{invoice}").json()
    assert receipt["number"] == "RE-2026-0815" and receipt["payment_reference"] == "RE-2026-0815"
    assert cockpit.get(receipt["file"]).content[:5] == b"%PDF-"
    assert cockpit.get(f"ki/receipts/{secret[0]['id']}").json()["fehler"] == "Diesen Beleg gibt es nicht."


def test_cards(cockpit, scanner):
    _setup(cockpit)
    mail = cockpit.get("ki/karten/mail").json()
    assert set(mail) == {"zahl", "text", "ton", "zeilen"} and len(mail["zeilen"]) <= 8
    pages = cockpit.get("ki/karten/pages").json()
    assert pages["zahl"] == "4" and pages["zeilen"][0]["wert"] == "4 / 300"


def test_reminder_joins_the_invoice_case(cockpit, scanner, mistral, store):
    _setup(cockpit)
    reminder = with_annotation(recorded("invoice"), kind="reminder", subject="Mahnung zu Rechnung Nr. RE-2026-0815")
    (scanner.folder / "scan_005.pdf").write_bytes(mistral.answer(letter(50), reminder))
    cockpit.sync_now()
    docs = {d["kind"]: d for d in store.documents()}
    assert docs["reminder"]["case_id"] and docs["reminder"]["case_id"] == docs["invoice"]["case_id"]
    full = cockpit.get(f"ki/documents/{docs['reminder']['id']}").json()
    assert [c["kind"] for c in full["case"]] == ["invoice"]


def test_court_letter_goes_to_the_owner_and_an_unclear_deadline_is_never_guessed(cockpit, scanner, mistral, store):
    unclear = {
        "kind": "court",
        "date": "",
        "amount": None,
        "certain": False,
        "text": "binnen zwei Wochen nach Zustellung",
    }
    court = with_annotation(
        recorded("invoice"),
        kind="court",
        subject="Ladung zur mündlichen Verhandlung",
        sender="Amtsgericht Musterstadt",
        file_number="12 C 345/26",
        action="deadline",
        due_dates=[unclear],
        amount=None,
        iban="",
        payment_reference="",
        is_receipt=False,
        confidential=False,
    )
    for f in scanner.folder.iterdir():
        if f.is_file():
            f.unlink()
    (scanner.folder / "summons.pdf").write_bytes(mistral.answer(letter(70), court))
    _setup(cockpit)
    doc = store.documents()[0]
    assert doc["status"] == "review" and doc["confidential"] == 1 and store.due_dates(doc["id"]) == []
    (event,) = cockpit.poll_events()
    assert event["art"] == "court" and event["data"]["owner_only"] is True
    assert "Eine Frist ist nicht eindeutig" in event["text"]
    card = cockpit.get("ki/karten/mail").json()
    assert card["ton"] == "kritisch" and card["zeilen"][0]["wert"] == "prüfen"
