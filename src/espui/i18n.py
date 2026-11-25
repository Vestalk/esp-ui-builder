"""Interface language: Ukrainian (the source texts) or English.

Every user-facing text is written in Ukrainian and wrapped in :func:`tr`; the
English texts live in :mod:`espui.i18n_en`, keyed by the Ukrainian ones. Texts
with values are templates: ``tr("Вибрано {n}").format(n=3)``.

The language is chosen once, when this module is first imported (module-level
titles are translated at import time), so a change applies after a restart:

1. ``ESPUI_LANG`` in the environment (``uk`` / ``en``; tests and the CLI);
2. the saved choice (``ui/language`` in the app's settings);
3. the system language: Ukrainian → ``uk``, anything else → ``en``.
"""

from __future__ import annotations

import locale
import os

LANGUAGES: dict[str, str] = {"uk": "Українська", "en": "English"}
DEFAULT = "uk"
SETTINGS_KEY = "ui/language"
ORGANIZATION = "ESP UI Builder"
APPLICATION = "ESP UI Builder"


def _saved() -> str | None:
    try:
        from PySide6.QtCore import QSettings
    except ImportError:  # pragma: no cover - PySide6 is a dependency
        return None
    value = QSettings(ORGANIZATION, APPLICATION).value(SETTINGS_KEY)
    return str(value) if value in LANGUAGES else None


def _system() -> str:
    code = ""
    try:
        from PySide6.QtCore import QLocale

        code = QLocale.system().name()
    except ImportError:  # pragma: no cover
        code = locale.getlocale()[0] or ""
    return "uk" if code.lower().startswith("uk") else "en"


def detect() -> str:
    env = os.environ.get("ESPUI_LANG", "").lower()[:2]
    if env in LANGUAGES:
        return env
    return _saved() or _system()


_language = detect()
_table: dict[str, str] = {}


def language() -> str:
    return _language


def set_language(code: str) -> None:
    """Switch for texts made from now on (module-level titles keep theirs)."""
    global _language, _table
    if code not in LANGUAGES:
        raise ValueError(f"unknown language {code!r}")
    _language = code
    _table = _load(code)


def save_language(code: str) -> None:
    """Remember the choice for the next start."""
    from PySide6.QtCore import QSettings

    QSettings(ORGANIZATION, APPLICATION).setValue(SETTINGS_KEY, code)


def _load(code: str) -> dict[str, str]:
    if code == "en":
        from espui.i18n_en import EN

        return EN
    return {}


def tr(text: str) -> str:
    """``text`` (Ukrainian) in the interface language."""
    return _table.get(text, text) if _table else text


_table = _load(_language)
