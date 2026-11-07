"""Texts people read, in the instance's language (`DMS_LANGUAGE`, de or en, fixed per instance).

German is the source; every key exists in English, too (tests/test_rules_and_texts.py). Values are str.format
templates: `t("x", name="Erika")`."""

from __future__ import annotations

from app import config
from app.texts import de, en

CATALOGUES = {"de": de.TEXTS, "en": en.TEXTS}


def t(key: str, **kw) -> str:
    text = CATALOGUES[config.settings.language].get(key) or CATALOGUES["de"][key]
    return text.format(**kw) if kw else text
