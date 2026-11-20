"""Bundled fonts, glyph sets and ui_fonts.py (stage 07)."""

from __future__ import annotations

from pathlib import Path

import pytest

from espui.assets.fonts import (
    ELLIPSIS,
    FONTS,
    UnknownFontError,
    font_info,
    font_path,
    has_glyph,
    rasterize,
)
from espui.core import serializer
from espui.core.models import Project
from espui.generators.micropython import fonts as gen_fonts
from espui.generators.micropython.generator import generate

ROOT = Path(__file__).resolve().parents[2]
UKRAINIAN_LETTERS = "АБВГҐДЕЄЖЗИІЇЙКЛМНОПРСТУФХЦЧШЩЬЮЯабвгґдеєжзиіїйклмнопрстуфхцчшщьюя"


@pytest.fixture(scope="module")
def weather() -> Project:
    return serializer.load(ROOT / "examples" / "weather.espui")


# ------------------------------------------------------------------ bundled fonts
@pytest.mark.parametrize("key", sorted(FONTS))
def test_fonts_cover_ukrainian(key: str) -> None:
    info = font_info(key)
    assert Path(font_path(key)).is_file()
    licence = Path(font_path(key)).with_name(info.license_file).read_text("utf-8")
    assert "SIL Open Font License, Version 1.1" in licence
    for char in UKRAINIAN_LETTERS + "ʼ°" + ELLIPSIS:
        assert has_glyph(key, char), (key, char)


def test_unknown_font() -> None:
    with pytest.raises(UnknownFontError, match="невідомий шрифт «comic»; є: serif, mono, pixel"):
        font_info("comic")


@pytest.mark.parametrize("size", [16, 24])
def test_pixel_font_lands_on_its_grid(size: int) -> None:
    """Press Start 2P at multiples of 8 px: every design pixel is an exact square, no blur."""
    cell = size // 8
    font = rasterize("pixel", size, UKRAINIAN_LETTERS + "0123456789°")
    for glyph in font.glyphs.values():
        assert glyph.left % cell == 0
        assert glyph.top % cell == 0
        assert glyph.width % cell == 0
        assert glyph.height % cell == 0
        for y in range(glyph.height):
            for x in range(glyph.width):
                assert glyph.pixel(x, y) == glyph.pixel(x - x % cell, y - y % cell), glyph.char


def test_glyphs_and_metrics() -> None:
    font = rasterize("serif", 16, "Київ")
    assert set(font.glyphs) == set("Київ?")  # '?' is always there
    assert font.title == "Literata 16 px"
    assert font.height == font.ascent + font.descent
    assert font.glyph("Ж") is font.glyphs["?"]  # not in the set
    k = font.glyphs["К"]
    assert k.stride == (k.width + 7) // 8
    assert len(k.rows) == k.stride * k.height
    assert font.width("Київ") == sum(font.glyphs[c].advance for c in "Київ")
    subset = font.subset("ї")
    assert set(subset.glyphs) == {"ї"}


def test_fit_with_ellipsis() -> None:
    font = rasterize("mono", 14, "Погода Київ" + ELLIPSIS)
    full = font.width("Погода Київ")
    assert font.fit("Погода Київ", full) == "Погода Київ"
    cut = font.fit("Погода Київ", full - 1)
    assert cut.endswith(ELLIPSIS)
    assert font.width(cut) <= full - 1
    assert font.fit("Погода", 0) == ""
    assert font.fit("Погода", font.width(ELLIPSIS)) == ELLIPSIS


def test_optical_size_follows_pixel_size() -> None:
    # Literata's opsz axis follows the size, so small text is drawn with a sturdier design.
    small, large = rasterize("serif", 8, "а"), rasterize("serif", 72, "а")
    assert small.glyphs["а"].width < large.glyphs["а"].width


# ------------------------------------------------------------------ glyph sets
def test_static_chars() -> None:
    assert gen_fonts.static_chars("%.1f°C") == "°C"
    assert gen_fonts.static_chars("Стан: %s (%d%%)") == "Стан:  (%)"


def test_example_char_sets(weather: Project) -> None:
    page = weather.pages[0]
    needs = gen_fonts.collect(page.widgets, page)
    assert set(needs) == {("serif", 12), ("serif", 14), ("serif", 16), ("serif", 40)}
    st_txt = needs[("serif", 12)]
    for text in ("Стан: ", "Перевірте: ", "Норма", "Увага", "Помилка"):  # format, condition, enum
        assert set(text) <= st_txt.static
    big = needs[("serif", 40)]  # t_val: "%.1f°C" -> number characters + °C
    assert big.static == set("°C")
    assert set("0123456789.-") <= big.dynamic
    assert set("ПЕРЕГРІВ") <= needs[("serif", 16)].static
    city = needs[("serif", 14)]  # str parameter: latin + Ukrainian
    assert set("Київ") <= city.all
    assert set("Lviv") <= city.all


@pytest.mark.parametrize(
    ("charset", "inside", "outside"),
    [("latin_uk", "Kyiv Київ", ""), ("latin", "Kyiv", "Київ"), ("digits", "12:30", "Kyiv")],
)
def test_str_charsets(charset: str, inside: str, outside: str) -> None:
    project = serializer.from_dict(
        {"pages": [{"name": "main",
                    "parameters": [{"name": "s", "type": "str", "charset": charset, "extra_chars": "№"}],
                    "widgets": [{"id": "t", "type": "text", "w": 100, "h": 20, "bind": "s", "format": "%s"}]}]}
    )  # fmt: skip
    page = project.pages[0]
    chars = gen_fonts.collect(page.widgets, page)[("serif", 16)].all
    assert set(inside) | {"№", "?", ELLIPSIS, " "} <= chars
    assert not set(outside) & chars - set(" ")


def test_chart_and_bar_chars() -> None:
    project = serializer.from_dict(
        {"pages": [{"name": "main",
                    "parameters": [{"name": "s", "type": "series", "x_kind": "label", "min": 0, "max": 9,
                                    "default": [{"x": "Пн", "y": 1}]},
                                   {"name": "n", "type": "int", "min": 0, "max": 9, "default": 1}],
                    "widgets": [{"id": "c", "type": "chart", "bind": "s", "chart": {"axis_y": "мм"}},
                                {"id": "b", "type": "bar", "bind": "n", "format": "Рівень"},
                                {"id": "a", "type": "arc", "bind": "n"},
                                {"id": "r", "type": "rect"}]}]}
    )  # fmt: skip
    page = project.pages[0]
    needs = gen_fonts.collect(page.widgets, page)
    assert set(needs) == {("serif", 8), ("serif", 12), ("serif", 14)}
    assert set("Пн" + "мм" + gen_fonts.NO_DATA) <= needs[("serif", 8)].static
    assert set("Рівень") <= needs[("serif", 12)].static
    assert set("0123456789") <= needs[("serif", 14)].dynamic


def test_missing_glyph_warning() -> None:
    project = serializer.from_dict(
        {"pages": [{"name": "main", "widgets": [
            {"id": "t", "type": "text", "w": 100, "h": 20, "format": "Сніг ❄ ☃"}]}]}
    )  # fmt: skip
    result = generate(project)
    assert result.warnings == ("Шрифт Literata не має символів '☃❄': на екрані буде «?».",)


# ------------------------------------------------------------------ ui_fonts.py
def test_example_fonts_module(weather: Project) -> None:
    result = generate(weather)
    source = result.files["ui_fonts.py"]
    assert len(source) <= 40 * 1024
    kb = f"{len(source) / 1024:.1f}".replace(".", ",")
    assert result.notes == (f"Шрифти: Literata 12/14/16/40 px — ui_fonts.py {kb} КБ",)
    text = source.decode()
    assert "SIL Open Font License 1.1" in text
    for name in ("SERIF_12", "SERIF_14", "SERIF_16", "SERIF_40"):
        assert f"\n{name} = Font(" in text


@pytest.mark.parametrize("text", ["Погода · Київ", "ПЕРЕГРІВ", "Вологість 40 %"])
@pytest.mark.parametrize("key", sorted(FONTS))
def test_spec_texts_have_every_glyph(key: str, text: str) -> None:
    font = rasterize(key, 16, text)
    assert all(c in font.glyphs for c in text)


def test_no_fonts_without_text() -> None:
    project = serializer.from_dict(
        {"pages": [{"name": "main", "widgets": [{"id": "r", "type": "rect"}]}]}
    )
    result = generate(project)
    assert "ui_fonts.py" not in result.files
    assert result.notes == ()
    assert "ui_fonts" not in result.files["ui_main.py"].decode()


def test_render_module_without_fonts() -> None:
    assert "class Font" in gen_fonts.render_module({})
