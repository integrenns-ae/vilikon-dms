"""Three invented letters from the scanner's SFTP folder, through the DMS, as the cockpit sees them."""

from conftest import SFTP_SOURCE, letter, recorded


def _setup(cockpit):
    r = cockpit.push_sources([SFTP_SOURCE])
    assert r.status_code == 200, r.text
    assert "passwort" not in r.json()["quellen"][0]
    return cockpit.sync_now()


def test_letters_are_read_filed_and_announced(cockpit, scanner, mistral, store):
    counts = _setup(cockpit)
    assert counts["neu"] == 3 and counts["gelesen"] == 3 and counts["fehler"] == 0
    assert counts["quellen"][0]["fehler"] == ""
    assert scanner.clients[-1].closed

    sent = mistral.requests[0]
    assert sent["model"] == "mistral-ocr-latest" and sent["_auth"] == "Bearer operator-key"
    assert sent["document_annotation_format"]["json_schema"]["strict"] is True

    docs = {d["art"]: d for d in store.documents()}
    assert set(docs) == {"rechnung", "bescheid", "werbung"}
    assert all(d["status"] == "fertig" for d in docs.values())
    invoice, notice = docs["rechnung"], docs["bescheid"]
    assert invoice["iban"] == "DE89370400440532013000" and invoice["betrag"] == 1190.0 and invoice["ist_beleg"] == 1
    assert notice["vertraulich"] == 1 and notice["seiten"] == 2
    assert [f["datum"] for f in store.deadlines(notice["id"])] == ["2026-11-16", "2026-12-07", "2027-03-10"]

    events = cockpit.poll_events()
    kinds = sorted(e["art"] for e in events)
    assert kinds == ["beleg", "zahlen", "zahlen"]  # advertising: nothing to do
    pay = next(e for e in events if e["art"] == "zahlen" and e["daten"]["dokument_id"] == invoice["id"])
    assert pay["titel"] == "Zahlen: Musterfirma GmbH – Rechnung Nr. RE-2026-0815"
    assert "1190.00 EUR" in pay["text"] and "2026-11-20" in pay["text"]
    assert pay["daten"]["iban"] == "DE89370400440532013000" and pay["daten"]["nur_inhaber"] is False
    assert cockpit.poll_events() == []

    log = cockpit.get("ki/protokoll").json()
    assert any("Gelesen: Finanzamt Musterstadt" in p["was"] for p in log)


def test_second_pass_and_same_letter_twice_are_not_read_again(cockpit, scanner, mistral, store):
    _setup(cockpit)
    calls = len(mistral.requests)
    again = cockpit.sync_now()
    assert again["neu"] == 0 and again["doppelt"] == 0 and len(mistral.requests) == calls
    # the same scan under another name (scanned twice, or photographed as well)
    (scanner.folder / "scan_004.pdf").write_bytes((scanner.folder / "scan_001.pdf").read_bytes())
    again = cockpit.sync_now()
    assert again["doppelt"] == 1 and len(store.documents()) == 3 and len(mistral.requests) == calls


def test_knowledge_files_for_the_company_memory(cockpit, scanner):
    _setup(cockpit)
    memory = cockpit.sync_knowledge()
    assert len(memory) == 3
    notice = next(f for f in memory.values() if f["meta"]["art"] == "bescheid")
    assert notice["sensibel"] is True
    assert notice["pfad"] == "Post/2026/2026-11-04 Finanzamt Musterstadt – Bescheid für 2025 über Einkommensteuer.md"
    assert notice["meta"]["fristen"] == ["2026-11-16", "2026-12-07", "2027-03-10"]
    assert "- Aktenzeichen: St.-Nr. 123/456/78901" in notice["text"] and "Rechtsbehelfsbelehrung" in notice["text"]
    assert sum(1 for f in memory.values() if f["sensibel"]) == 1
    versions = {k: v["version"] for k, v in memory.items()}
    assert {k: v["version"] for k, v in cockpit.sync_knowledge().items()} == versions


def test_functions_for_employees(cockpit, scanner, store):
    _setup(cockpit)
    found = cockpit.get("ki/dokumente", who="anna", suche="Musterfirma").json()["dokumente"]
    assert [d["art"] for d in found] == ["rechnung"]
    # the tax notice is confidential: not without the right, found with it
    assert cockpit.get("ki/dokumente", suche="Finanzamt").json()["dokumente"] == []
    secret = cockpit.get("ki/vertraulich/dokumente", suche="Finanzamt").json()["dokumente"]
    assert len(secret) == 1
    assert cockpit.get(f"ki/dokumente/{secret[0]['id']}").status_code == 404
    full = cockpit.get(f"ki/vertraulich/dokumente/{secret[0]['id']}").json()
    assert full["betrag"] == 842.0 and len(full["fristen"]) == 3

    due = cockpit.get("ki/fristen", von="2026-11-01", bis="2026-12-31").json()["fristen"]
    assert [(f["datum"], f["art"]) for f in due] == [
        ("2026-11-16", "zahlung"),
        ("2026-11-20", "zahlung"),
        ("2026-12-07", "widerspruch"),
    ]
    assert due[0]["vertraulich"] is True and due[0]["absender"] == "Vertraulicher Brief" and due[0]["betrag"] is None
    assert due[1]["absender"] == "Musterfirma GmbH" and due[1]["betrag"] == 1190.0

    invoice = found[0]["id"]
    receipt = cockpit.get(f"ki/belege/{invoice}").json()
    assert receipt["nummer"] == "RE-2026-0815" and receipt["verwendungszweck"] == "RE-2026-0815"
    assert cockpit.get(receipt["datei"]).content[:5] == b"%PDF-"
    assert cockpit.get(f"ki/belege/{secret[0]['id']}").json()["fehler"] == "Diesen Beleg gibt es nicht."


def test_cards(cockpit, scanner, store):
    _setup(cockpit)
    post = cockpit.get("ki/karten/post").json()
    assert set(post) == {"zahl", "text", "ton", "zeilen"} and len(post["zeilen"]) <= 8
    pages = cockpit.get("ki/karten/seiten").json()
    assert pages["zahl"] == "4" and pages["zeilen"][0]["wert"] == "4 / 300"


def test_reminder_joins_the_invoice_case(cockpit, scanner, mistral, store):
    _setup(cockpit)
    reminder = recorded("rechnung")
    reminder["document_annotation"] = (
        reminder["document_annotation"]
        .replace('"rechnung"', '"mahnung"')
        .replace("Rechnung Nr.", "Mahnung zu Rechnung Nr.")
    )
    (scanner.folder / "scan_005.pdf").write_bytes(mistral.answer(letter(50), reminder))
    cockpit.sync_now()
    docs = {d["art"]: d for d in store.documents()}
    assert docs["mahnung"]["fall_id"] and docs["mahnung"]["fall_id"] == docs["rechnung"]["fall_id"]
    full = cockpit.get(f"ki/dokumente/{docs['mahnung']['id']}").json()
    assert [c["art"] for c in full["fall"]] == ["rechnung"]


def test_court_letter_goes_to_the_owner_and_an_unclear_deadline_is_never_guessed(cockpit, scanner, mistral, store):
    court = recorded("rechnung")
    court["document_annotation"] = (
        '{"art": "gericht", "betreff": "Ladung zur mündlichen Verhandlung", "absender": "Amtsgericht Musterstadt", '
        '"datum": "2026-11-03", "aktenzeichen": "12 C 345/26", "handlung": "frist", "fristen": [{"art": "gericht", '
        '"datum": "", "betrag": null, "sicher": false, "text": "binnen zwei Wochen nach Zustellung"}], "betrag": null, '
        '"iban": "", "verwendungszweck": "", "ist_beleg": false, "vertraulich": false}'
    )
    for f in scanner.folder.iterdir():
        if f.is_file():
            f.unlink()
    (scanner.folder / "ladung.pdf").write_bytes(mistral.answer(letter(70), court))
    _setup(cockpit)
    doc = store.documents()[0]
    assert doc["status"] == "pruefen" and doc["vertraulich"] == 1 and store.deadlines(doc["id"]) == []
    (event,) = cockpit.poll_events()
    assert event["art"] == "gericht" and event["daten"]["nur_inhaber"] is True
    assert "Eine Frist ist nicht eindeutig" in event["text"]
    card = cockpit.get("ki/karten/post").json()
    assert card["ton"] == "kritisch" and card["zeilen"][0]["wert"] == "prüfen"
