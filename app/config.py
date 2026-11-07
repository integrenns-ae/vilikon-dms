"""Settings from the environment. Everything secret the cockpit pushes later (`PUT ki/quellen`) lives in the store,
not here; only the service token and the operator's Mistral key come from the container's environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class Settings:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "data")))
    # The cockpit sends it as `Authorization: Bearer …` on every ki/ call. Empty: every ki/ call is refused.
    token: str = field(default_factory=lambda: os.environ.get("DMS_TOKEN", ""))
    language: str = field(default_factory=lambda: os.environ.get("DMS_SPRACHE", "de"))
    mistral_api_key: str = field(default_factory=lambda: os.environ.get("MISTRAL_API_KEY", ""))
    mistral_ocr_model: str = field(default_factory=lambda: os.environ.get("MISTRAL_OCR_MODEL", "mistral-ocr-latest"))
    # Pages per calendar month on the operator's key; 0 = no cap. An own key of the customer lifts it.
    pages_per_month: int = field(default_factory=lambda: _int("DMS_SEITEN_MONAT", 500))
    intake_interval_min: int = field(default_factory=lambda: _int("DMS_INTERVALL_MIN", 10))

    def __post_init__(self) -> None:
        if self.language not in ("de", "en"):
            self.language = "de"


settings = Settings()


def reload() -> Settings:
    """Read the environment again (tests)."""
    global settings
    settings = Settings()
    return settings
