"""Pages per calendar month. The operator offers the DMS for free with a cap per instance (`DMS_SEITEN_MONAT`); at the
cap a document waits (status `wartet`) and goes on, oldest first, when the next month starts. With an own Mistral key
of the customer (pushed by the cockpit in `PUT ki/quellen`) there is no cap: the pages are on the customer's bill."""

from __future__ import annotations

from datetime import UTC, datetime

from app import config
from app.store import Store

OWN_KEY = "mistral_schluessel"


def month(at: datetime | None = None) -> str:
    return (at or datetime.now(UTC)).strftime("%Y-%m")


def own_key(store: Store) -> str:
    return store.value(OWN_KEY)


def api_key(store: Store) -> str:
    return own_key(store) or config.settings.mistral_api_key


def cap(store: Store) -> int:
    """0 = no cap."""
    return 0 if own_key(store) else max(0, config.settings.pages_per_month)


def fits(store: Store, pages: int, at: datetime | None = None) -> bool:
    limit = cap(store)
    return not limit or store.pages_used(month(at)) + pages <= limit


def too_big(store: Store, pages: int) -> bool:
    """A document that alone is more than a month's pages would wait forever."""
    limit = cap(store)
    return bool(limit) and pages > limit


def book(store: Store, pages: int, at: datetime | None = None) -> None:
    store.add_pages(month(at), pages)


def state(store: Store, at: datetime | None = None) -> dict:
    used, limit = store.pages_used(month(at)), cap(store)
    return {
        "monat": month(at),
        "seiten": used,
        "grenze": limit or None,
        "eigener_schluessel": bool(own_key(store)),
        "wartend": len(store.documents(status=("wartet",))),
    }
