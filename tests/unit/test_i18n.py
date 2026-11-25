"""English interface: every text has a translation with the same placeholders."""

from __future__ import annotations

import ast
import json
import os
import re
import string
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from espui import i18n
from espui.i18n_en import EN

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "espui"
CYRILLIC = re.compile(r"[А-Яа-яІіЇїЄєҐґ]")
# Texts deliberately not translated: data, or shown the same in both languages.
NOT_TRANSLATED = {
    "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюяʼ’«»—–…№°",  # glyphs
    "Українська",  # the language's own name
    "Мова / Language",
}


def _sources() -> list[Path]:
    return [
        f
        for f in sorted(SRC.rglob("*.py"))
        if "runtime" not in f.parts and not f.name.startswith("i18n")
    ]


def _keys() -> dict[str, str]:
    """Every literal passed to tr() -> where it is."""
    keys: dict[str, str] = {}
    for f in _sources():
        for node in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                keys.setdefault(node.args[0].value, f"{f.relative_to(ROOT)}:{node.lineno}")
    for y in sorted((SRC / "displays").glob("*.yaml")):
        title = yaml.safe_load(y.read_text("utf-8"))["title"]
        keys.setdefault(title, str(y.relative_to(ROOT)))
    return keys


def _fields(text: str) -> list[str]:
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)


def test_every_text_has_an_english_translation() -> None:
    missing = [
        f"{where}: {key!r}"
        for key, where in _keys().items()
        if CYRILLIC.search(key) and key not in NOT_TRANSLATED and key not in EN
    ]
    assert missing == []


def _formatted() -> set[str]:
    """Keys used as templates: tr("…").format(…)."""
    out: set[str] = set()
    for f in _sources():
        for node in ast.walk(ast.parse(f.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "format"
                and isinstance(node.func.value, ast.Call)
                and isinstance(node.func.value.func, ast.Name)
                and node.func.value.func.id == "tr"
                and isinstance(node.func.value.args[0], ast.Constant)
            ):
                out.add(node.func.value.args[0].value)
    return out


def test_translations_keep_placeholders_and_are_english() -> None:
    keys, templates = _keys(), _formatted()
    for key, english in EN.items():
        assert key in keys, f"unused translation: {key[:60]!r}"
        assert not CYRILLIC.search(english), english
        if key in templates:
            assert _fields(key) == _fields(english), key[:60]


def test_no_ukrainian_text_outside_tr() -> None:
    """A new Ukrainian string must go through tr() (docstrings and comments don't count)."""
    found = []
    for f in _sources():
        tree = ast.parse(f.read_text("utf-8"))
        wrapped: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                wrapped.add(id(node.value))  # docstrings
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "tr"
            ):
                wrapped.update(id(a) for a in node.args)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in wrapped
                and CYRILLIC.search(node.value)
                and node.value not in NOT_TRANSLATED
                and not node.value.startswith("Мову інтерфейсу")  # the bilingual restart question
            ):
                found.append(f"{f.relative_to(ROOT)}:{node.lineno}: {node.value[:50]!r}")
    assert found == []


def test_tr_follows_the_language() -> None:
    assert i18n.language() == "uk"  # tests/conftest.py
    assert i18n.tr("Зберегти") == "Зберегти"
    try:
        i18n.set_language("en")
        assert i18n.tr("Зберегти") == "Save"
        selected = i18n.tr(
            "Вибрано {v1}: {shown}.{group} Колір і непрозорість — для всіх одразу; "
            "перетягування й стрілки рухають усі разом."
        )
        assert selected.startswith("Selected {v1}")
        assert i18n.tr("щось без перекладу") == "щось без перекладу"
    finally:
        i18n.set_language("uk")
    with pytest.raises(ValueError, match="unknown language"):
        i18n.set_language("de")


def test_language_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ESPUI_LANG", "en")
    assert i18n.detect() == "en"
    monkeypatch.setenv("ESPUI_LANG", "uk_UA")
    assert i18n.detect() == "uk"


@pytest.mark.gui
def test_the_window_in_english() -> None:
    """A fresh process with ESPUI_LANG=en: menus, panels and messages in English."""
    script = """
import json
from PySide6.QtWidgets import QApplication
app = QApplication([])
from espui.gui.main_window import MainWindow
from espui.core.checks import check_project
from espui.gui.document import new_project
w = MainWindow()
p = new_project()
p.pages[0].widgets = []
print(json.dumps({
    "menus": [a.text() for a in w.menuBar().actions()],
    "empty": w.properties.empty.text(),
    "generate": w.act_generate.text(),
    "issue": [i.message for i in check_project(
        p.model_copy(update={"display": p.display.model_copy(update={"spi_hz": 999_000_000})})
    )],
}))
"""
    env = {**os.environ, "ESPUI_LANG": "en", "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["menus"] == [
        "File",
        "Edit",
        "Arrange",
        "View",
        "Display",
        "Pages",
        "Parameters",
        "Generate",
        "Help",
    ]
    assert out["empty"] == "Select a widget on the canvas or in the layers."
    assert out["generate"] == "▶ Generate…"
    assert out["issue"]  # the check's message itself is translated too
    assert any(m.startswith("at most") for m in out["issue"]), out["issue"]
    assert not any(CYRILLIC.search(m) for m in out["issue"])
