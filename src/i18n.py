"""Label lookup by language from config/i18n/*.json."""
import json

from src.paths import CONFIG


def load(lang):
    with open(CONFIG / "i18n" / f"{lang}.json", encoding="utf-8") as f:
        return json.load(f)
