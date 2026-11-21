"""Pages per calendar month. The operator offers the DMS with his own Mistral key and a cap per instance: the vault entry
`OCR` then carries `OCR_BETREIBER=ja` and `OCR_PAGES_PER_MONTH`. At the cap a document waits (status `waiting`) and
goes on, oldest first, when the next month starts. A customer's own key (no `OCR_BETREIBER`) has no cap: the pages are
on the customer's bill. Standalone, `MISTRAL_API_KEY` stands in for `OCR_PASSWORT` and `DMS_PAGES_PER_MONTH` for the
cap."""

from __future__ import annotations

from datetime import UTC, datetime

from app import config
from app.store import Store

SERVICE = "mistral"  # the only OCR the DMS speaks


def month(at: datetime | None = None) -> str:
    return (at or datetime.now(UTC)).strftime("%Y-%m")


def wrong_service() -> bool:
    return config.settings.ocr_service not in ("", SERVICE)


def api_key() -> str:
    return "" if wrong_service() else config.settings.ocr_key


def operator() -> bool:
    return config.settings.ocr_operator


def cap() -> int:
    """0 = no cap."""
    return max(0, config.settings.pages_per_month) if operator() else 0


def fits(store: Store, pages: int, at: datetime | None = None) -> bool:
    limit = cap()
    return not limit or store.pages_used(month(at)) + pages <= limit


def too_big(pages: int) -> bool:
    """A document that alone is more than a month's pages would wait forever."""
    limit = cap()
    return bool(limit) and pages > limit


def book(store: Store, pages: int, at: datetime | None = None) -> None:
    store.add_pages(month(at), pages)


def state(store: Store, at: datetime | None = None) -> dict:
    used, limit = store.pages_used(month(at)), cap()
    return {
        "month": month(at),
        "pages": used,
        "cap": limit or None,
        "own_key": bool(api_key()) and not operator(),
        "waiting": len(store.documents(status=("waiting",))),
    }
