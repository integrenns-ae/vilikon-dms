"""Texts people read, in the instance's language (`DMS_SPRACHE`, de or en, fixed per instance).

German is the source; every key exists in English, too (tests/test_texte.py). Values are str.format templates:
`t("x", name="Erika")`."""

from __future__ import annotations

from app import config
from app.texte import dms_de, dms_en

CATALOGUES = {"de": dms_de.TEXTE, "en": dms_en.TEXTE}


def t(key: str, **kw) -> str:
    text = CATALOGUES[config.settings.language].get(key) or CATALOGUES["de"][key]
    return text.format(**kw) if kw else text
