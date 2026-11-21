"""Settings from the environment, read once at start. Nothing secret is kept in the store.

As a Vilikon Werkzeug the Verwalter sets them: the basics (`PORT`, `HOST`, `DATA_DIR`, …), `VILIKON_TOKEN`,
`VILIKON_LANGUAGE`, and every vault entry the owner released for the DMS as `<NAME>_ART=<vault type>`,
`<NAME>_<KEY>` and `<NAME>_PASSWORT`: the OCR key as `OCR_*` (here), the file stores as `SCANNER_*`, `SCANNER2_*` …
(app/intake/env_sources.py, read on every pass). Standalone, `DMS_*` and `MISTRAL_API_KEY` stand in."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

TRUE = ("1", "true", "ja", "yes")


def _env(*names: str, default: str = "") -> str:
    """The first of these variables that is set."""
    return next((v for v in (os.environ.get(n, "").strip() for n in names) if v), default)


def _int(*names: str, default: int) -> int:
    try:
        return int(_env(*names) or default)
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "data")))
    # The core sends the per-tool token as `X-Vilikon-Token`; standalone, `DMS_TOKEN` as `Authorization: Bearer …`.
    # Both empty: everything but /health is refused.
    vilikon_token: str = field(default_factory=lambda: os.environ.get("VILIKON_TOKEN", ""))
    token: str = field(default_factory=lambda: os.environ.get("DMS_TOKEN", ""))
    language: str = field(default_factory=lambda: _env("VILIKON_LANGUAGE", "DMS_LANGUAGE", default="de"))
    # The vault entry OCR (type api_key): the operator's Mistral key with OCR_BETREIBER=ja and a cap, or the
    # customer's own key without either.
    ocr_key: str = field(default_factory=lambda: _env("OCR_PASSWORT", "MISTRAL_API_KEY"))
    ocr_service: str = field(default_factory=lambda: _env("OCR_SERVICE").lower())
    ocr_operator: bool = field(default_factory=lambda: _env("OCR_BETREIBER").lower() in TRUE)
    # Pages per calendar month on the operator's key; 0 = no cap.
    pages_per_month: int = field(
        default_factory=lambda: _int("OCR_PAGES_PER_MONTH", "DMS_PAGES_PER_MONTH", default=500)
    )
    mistral_ocr_model: str = field(default_factory=lambda: _env("MISTRAL_OCR_MODEL", default="mistral-ocr-latest"))
    intake_interval_min: int = field(default_factory=lambda: _int("DMS_INTERVAL_MIN", default=10))
    # A letter from a file store's first fetch dated more than this many days before it came in is only filed;
    # 0 = every letter is announced.
    archive_days: int = field(default_factory=lambda: max(0, _int("DMS_ARCHIVE_DAYS", default=30)))

    def __post_init__(self) -> None:
        if self.language not in ("de", "en"):
            self.language = "de"


settings = Settings()


def reload() -> Settings:
    """Read the environment again (tests)."""
    global settings
    settings = Settings()
    return settings
