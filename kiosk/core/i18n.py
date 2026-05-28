import json
from functools import lru_cache

from flask import current_app


FALLBACK_LANGUAGE = "en"
SUPPORTED_LANGUAGES = {"ru", "en", "de"}


def normalize_language(language):
    if language in SUPPORTED_LANGUAGES:
        return language

    return FALLBACK_LANGUAGE


@lru_cache(maxsize=8)
def load_language_file(translations_dir, language):
    path = translations_dir / f"{language}.json"

    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}


def translate(key, language=None):
    active_language = normalize_language(language)
    translations_dir = current_app.config["RESOURCE_DIR"] / "kiosk" / "translations"
    active_translations = load_language_file(translations_dir, active_language)
    fallback_translations = load_language_file(translations_dir, FALLBACK_LANGUAGE)

    return active_translations.get(key, fallback_translations.get(key, key))
