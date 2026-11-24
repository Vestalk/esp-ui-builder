"""Structure (pydantic) and cross-field checks, with Ukrainian messages and paths."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from espui.core.checks import check_project, validate_project
from espui.core.hardware import Chip, Driver
from espui.core.issues import ProjectValidationError, issues_from_validation_error
from espui.core.models import Condition, MappingRule, Project, Widget
from tests.unit.core.conftest import (
    FLAG,
    LEVEL,
    MODE,
    NAME,
    SERIES,
    TEMP,
    make_project,
    paths,
    project_dict,
)


def structure_issues(data: dict[str, Any]) -> list[str]:
    with pytest.raises(ValidationError) as info:
        Project.model_validate(data)
    return [str(i) for i in issues_from_validation_error(info.value)]


def check(**kwargs: Any) -> list[str]:
    return [str(i) for i in check_project(make_project(**kwargs))]


# ------------------------------------------------------------------ minimal project
def test_minimal_project_is_valid_and_complete() -> None:
    project = make_project()
    assert check_project(project) == []
    assert project.display.size == (240, 320)
    assert project.display.pins.assigned() == {
        "sck": 12,
        "mosi": 11,
        "dc": 9,
        "cs": 10,
        "rst": 8,
        "bl": 7,
    }
    assert validate_project(project) is project


def test_project_needs_a_page() -> None:
    assert structure_issues({"pages": []}) == ["pages: щонайменше 1 елемент(и)"]


def test_rotation_swaps_size() -> None:
    project = make_project(display={"rotation": 1})
    assert project.display.size == (320, 240)


# ------------------------------------------------------------------ names
@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("", "назва порожня"),
        ("Temp", "лише латинські малі літери"),
        ("1st", "лише латинські малі літери"),
        ("температура", "лише латинські малі літери"),
        ("a" * 33, "до 32 символів"),
        ("class", "«class» — зарезервоване слово Python"),
        ("self", "зарезервоване слово"),
    ],
)
def test_bad_parameter_names(name: str, message: str) -> None:
    issues = structure_issues(project_dict([{**FLAG, "name": name}]))
    assert len(issues) == 1
    assert issues[0].startswith("pages[0].parameters[0].name: ")
    assert message in issues[0]


@pytest.mark.parametrize("name", ["display", "st7789", "fonts"])
def test_reserved_page_names(name: str) -> None:
    data = {"pages": [{"name": name}]}
    assert structure_issues(data) == [f"pages[0].name: ui_{name}.py вже зайнято спільним файлом"]


def test_duplicate_names() -> None:
    data = project_dict([FLAG, FLAG], [{"id": "a", "type": "rect"}, {"id": "a", "type": "rect"}])
    data["pages"].append({"name": "main"})
    issues = check_project(Project.model_validate(data))
    assert paths(issues) == [
        "pages[0].parameters[1].name",
        "pages[0].widgets[1].id",
        "pages[1].name",
    ]
    assert "параметр «on» вже є" in str(issues[0])


# ------------------------------------------------------------------ parameters
@pytest.mark.parametrize(
    ("param", "path", "message"),
    [
        ({**TEMP, "min": 10, "max": 10}, "max", "max має бути більше за min"),
        ({**TEMP, "default": 101}, "default", "в межах 0…100"),
        ({**TEMP, "default": -0.5}, "default", "в межах 0…100"),
        ({**LEVEL, "default": 11}, "default", "в межах 0…10"),
        ({**NAME, "default": "12345678"}, "default", "довше за 7 символів"),
        ({**MODE, "default": "z"}, "default", "одним з варіантів: a, b, c"),
        ({**MODE, "values": ["a", "a"]}, "values", "варіанти повторюються: a"),
        ({**MODE, "values": ["a", ""]}, "values", "порожній варіант"),
        ({**SERIES, "min": 5, "max": 1}, "max", "більше за min"),
    ],
)
def test_parameter_checks(param: dict[str, Any], path: str, message: str) -> None:
    issues = check(parameters=[param])
    assert len(issues) == 1, issues
    assert issues[0].startswith(f"pages[0].parameters[0].{path}: ")
    assert message in issues[0]


@pytest.mark.parametrize(
    "param",
    [
        {**TEMP, "default": 0},
        {**TEMP, "default": 100},
        {**LEVEL, "default": 0},
        {**LEVEL, "default": 10},
        {**NAME, "default": "1234567"},
        FLAG,
        MODE,
        SERIES,
        {**SERIES, "x_kind": "label", "default": [{"x": "пн", "y": 1}, {"x": "вт", "y": 2}]},
    ],
)
def test_parameter_boundaries_are_valid(param: dict[str, Any]) -> None:
    assert check(parameters=[param]) == []


@pytest.mark.parametrize(
    ("param", "message"),
    [
        ({**NAME, "max_len": 1}, "max_len: має бути не менше 2"),
        ({**NAME, "max_len": 129}, "max_len: має бути не більше 128"),
        ({**SERIES, "max_points": 1}, "max_points: має бути не менше 2"),
        ({**SERIES, "max_points": 257}, "max_points: має бути не більше 256"),
        ({**MODE, "values": ["a"]}, "values: щонайменше 2 елемент(и)"),
        ({**LEVEL, "default": 1.5}, "default: очікується ціле число"),
        ({"name": "x", "type": "complex"}, "невідомий вид запису"),
    ],
)
def test_parameter_structure(param: dict[str, Any], message: str) -> None:
    issues = structure_issues(project_dict([param]))
    assert any(message in i for i in issues), issues


def test_enum_default_is_first_value() -> None:
    page = make_project(parameters=[MODE]).pages[0]
    assert page.parameters[0].default == "a"
    assert page.value_of("mode") == "a"
    assert page.value_of("missing") is None


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([{"x": i, "y": 1} for i in range(5)], "максимум 4 точок"),
        ([{"x": 1, "y": 1}, {"x": 1, "y": 2}], "ключі x мають бути різними"),
        ([{"x": "пн", "y": 1}], "ключ x «пн» має бути числом"),
    ],
)
def test_series_default(points: list[dict[str, Any]], message: str) -> None:
    issues = check(parameters=[{**SERIES, "default": points}])
    assert issues == [f"pages[0].parameters[0].default: {message}"]


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([{"x": 1, "y": 1}], "ключ x «1.0» має бути міткою (рядком)"),
        ([{"x": "довгамітка", "y": 1}], "мітка «довгамітка» довша за 7 символів"),
    ],
)
def test_series_labels(points: list[dict[str, Any]], message: str) -> None:
    issues = check(parameters=[{**SERIES, "x_kind": "label", "default": points}])
    assert issues == [f"pages[0].parameters[0].default: {message}"]


def test_test_values() -> None:
    project = make_project(parameters=[TEMP, FLAG])
    page = project.pages[0]
    page.test_values = {"t": 120.0, "on": True, "ghost": 1}
    assert [str(i) for i in check_project(project)] == [
        "pages[0].test_values.t: значення має бути в межах 0…100",
        "pages[0].test_values.ghost: немає параметра «ghost»",
    ]
    assert page.value_of("on") is True
    assert page.value_of("t") == 120.0


@pytest.mark.parametrize(
    ("param", "value", "message"),
    [
        (FLAG, 1, "очікується true або false"),
        (LEVEL, "5", "очікується ціле число"),
        (TEMP, "5", "очікується число"),
        (NAME, 5, "очікується рядок"),
        (SERIES, 5, "очікується список точок {x, y}"),
    ],
)
def test_test_value_types(param: dict[str, Any], value: Any, message: str) -> None:
    project = make_project(parameters=[param])
    project.pages[0].test_values = {param["name"]: value}
    assert [i.message for i in check_project(project)] == [message]


# ------------------------------------------------------------------ widgets
def test_widget_type_defaults() -> None:
    widgets = (
        make_project(
            widgets=[
                {"id": "a", "type": "text"},
                {"id": "b", "type": "rect"},
                {"id": "c", "type": "image"},
                {"id": "d", "type": "chart"},
            ]
        )
        .pages[0]
        .widgets
    )
    assert (widgets[0].font, widgets[0].font_size) == ("serif", 16)
    assert (widgets[1].font, widgets[1].font_size) == (None, None)
    assert widgets[2].image is not None
    assert widgets[2].image.fit == "contain"
    assert widgets[3].chart is not None
    assert widgets[3].chart.style == "line"
    assert widgets[3].font == "serif"
    assert widgets[3].font_size is None


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("color", "red", "колір має бути у форматі #rrggbb"),
        ("opacity", 101, "має бути не більше 100"),
        ("font_size", 7, "має бути не менше 8"),
        ("font_size", 73, "має бути не більше 72"),
        ("font", "comic", "допустимі значення"),
        ("type", "button", "допустимі значення"),
        ("w", -1, "має бути не менше 0"),
        ("pivot", "middle", "допустимі значення"),
        ("x", "abc", "очікується ціле число"),
    ],
)
def test_widget_structure(field: str, value: Any, message: str) -> None:
    issues = structure_issues(project_dict(widgets=[{"id": "a", "type": "text", field: value}]))
    assert any(i.startswith(f"pages[0].widgets[0].{field}") and message in i for i in issues), (
        issues
    )


def test_colors_are_normalized() -> None:
    widget = (
        make_project(widgets=[{"id": "a", "type": "rect", "color": "#ABC"}]).pages[0].widgets[0]
    )
    assert widget.color == "#aabbcc"


@pytest.mark.parametrize(
    ("widget_type", "param", "ok"),
    [
        ("text", TEMP, True),
        ("text", FLAG, True),
        ("text", MODE, True),
        ("text", NAME, True),
        ("text", SERIES, False),
        ("value", TEMP, True),
        ("value", LEVEL, True),
        ("value", NAME, False),
        ("bar", LEVEL, True),
        ("bar", FLAG, False),
        ("arc", TEMP, True),
        ("arc", MODE, False),
        ("image", NAME, True),
        ("image", TEMP, False),
        ("chart", SERIES, True),
        ("chart", TEMP, False),
        ("rect", TEMP, False),
        ("circle", FLAG, False),
        ("line", LEVEL, False),
    ],
)
def test_bindings(widget_type: str, param: dict[str, Any], ok: bool) -> None:
    widget = {"id": "w", "type": widget_type, "bind": param["name"], "w": 10}
    issues = check(parameters=[param], widgets=[widget])
    if ok:
        assert issues == []
    else:
        assert issues == [
            f"pages[0].widgets[0].bind: до «{widget_type}» не можна прив'язати параметр "
            f"типу {param['type']}"
        ]


def test_widget_checks() -> None:
    issues = check(
        widgets=[
            {"id": "a", "type": "text", "bind": "ghost", "format": "%x"},
            {"id": "b", "type": "rect", "font": "mono", "font_size": 12},
            {"id": "c", "type": "chart", "rotation_deg": 45, "chart": {"y_min": 5, "y_max": 5}},
            {"id": "d", "type": "line"},
            {"id": "e", "type": "image", "image": {"file": "nope"}},
        ]
    )
    assert issues == [
        "pages[0].widgets[0].format: «%x» не підтримується; можна %s, %d, %.Nf, %%",
        "pages[0].widgets[0].bind: немає параметра «ghost»",
        "pages[0].widgets[1].font: шрифт не застосовується до «rect»",
        "pages[0].widgets[1].font_size: розмір шрифту не застосовується до «rect»",
        "pages[0].widgets[2].rotation_deg: графік не повертається",
        "pages[0].widgets[2].chart.y_max: y_max має бути більше за y_min",
        "pages[0].widgets[3].w: лінія нульової довжини",
        "pages[0].widgets[4].image.file: немає картинки «nope»",
    ]


def test_empty_bind_and_image_file_become_none() -> None:
    widget = make_project(widgets=[{"id": "a", "type": "image", "bind": "", "image": {"file": ""}}])
    w = widget.pages[0].widgets[0]
    assert w.bind is None
    assert w.image is not None
    assert w.image.file is None


# ------------------------------------------------------------------ rules
def rule_issues(rule: dict[str, Any], widget_type: str = "text", params: Any = None) -> list[str]:
    return check(
        parameters=params or [TEMP, FLAG, MODE, NAME, SERIES],
        widgets=[{"id": "w", "type": widget_type, "rules": [rule]}],
    )


def test_rule_kinds_are_parsed() -> None:
    widget = Widget.model_validate(
        {
            "id": "w",
            "type": "text",
            "rules": [
                {"if": ["t", "≥", 30], "set": "color", "to": "#ff0000"},
                {"param": "t", "prop": "x", "at_min": 0, "at_max": 100},
            ],
        }
    )
    condition, mapping = widget.rules
    assert isinstance(condition, Condition)
    assert (condition.param, condition.op, condition.value) == ("t", ">=", 30)
    assert isinstance(mapping, MappingRule)
    assert list(widget.conditions()) == [condition]
    assert list(widget.mappings()) == [mapping]
    assert widget.dependencies() == {"t"}


@pytest.mark.parametrize(
    ("rule", "widget_type", "message"),
    [
        ({"if": ["ghost", "==", 1], "set": "x", "to": 1}, "text", "if[0]: немає параметра «ghost»"),
        ({"if": ["s", "==", 1], "set": "x", "to": 1}, "text", "if[0]: умова не може залежати від series"),
        ({"if": ["on", ">", True], "set": "x", "to": 1}, "text", "if[1]: для bool можна лише: =="),
        ({"if": ["mode", ">", "a"], "set": "x", "to": 1}, "text", "if[1]: для enum можна лише: ==, !="),
        ({"if": ["mode", "==", "z"], "set": "x", "to": 1}, "text", "if[2]: має бути одним з варіантів"),
        ({"if": ["t", ">", "hot"], "set": "x", "to": 1}, "text", "if[2]: очікується число"),
        ({"if": ["t", ">", 1], "set": "text", "to": "a"}, "rect", "set: «text» не змінюється для «rect»"),
        ({"if": ["t", ">", 1], "set": "angle", "to": 9}, "chart", "set: «angle» не змінюється для «chart»"),
        ({"if": ["t", ">", 1], "set": "color", "to": "red"}, "text", "to: колір у форматі #rrggbb"),
        ({"if": ["t", ">", 1], "set": "visible", "to": 1}, "text", "to: очікується true (показати)"),
        ({"if": ["t", ">", 1], "set": "opacity", "to": 150}, "text", "to: непрозорість від 0 до 100 %"),
        ({"if": ["t", ">", 1], "set": "x", "to": "a"}, "text", "to: очікується число"),
        ({"if": ["t", ">", 1], "set": "text", "to": 5}, "text", "to: очікується рядок"),
        ({"param": "ghost", "prop": "x", "at_min": 0, "at_max": 1}, "text", "param: немає параметра"),
        ({"param": "on", "prop": "x", "at_min": 0, "at_max": 1}, "text", "param: залежність можлива лише від float або int"),
        ({"param": "t", "prop": "angle", "at_min": 0, "at_max": 1}, "chart", "prop: «angle» не змінюється для «chart»"),
        ({"param": "t", "prop": "opacity", "at_min": 0, "at_max": 200}, "text", "at_max: непрозорість від 0 до 100 %"),
    ],
)  # fmt: skip
def test_rule_checks(rule: dict[str, Any], widget_type: str, message: str) -> None:
    issues = rule_issues(rule, widget_type)
    assert len(issues) == 1, issues
    assert issues[0].startswith("pages[0].widgets[0].rules[0].")
    assert message in issues[0], issues


@pytest.mark.parametrize(
    "rule",
    [
        {"if": ["t", ">", 1000], "set": "x", "to": 1},  # outside the range is fine for a comparison
        {"if": ["on", "==", True], "set": "visible", "to": False},
        {"if": ["mode", "!=", "b"], "set": "color", "to": "#00ff00"},
        {"if": ["label", "==", "hi"], "set": "text", "to": "hello"},
        {"param": "t", "prop": "y", "at_min": -10, "at_max": 300},
    ],
)
def test_valid_rules(rule: dict[str, Any]) -> None:
    assert rule_issues(rule) == []


def test_rule_structure() -> None:
    issues = structure_issues(
        project_dict(
            widgets=[
                {"id": "w", "type": "text", "rules": [{"if": ["t", "~", 1], "set": "x", "to": 1}]}
            ]
        )
    )
    assert any(i.startswith("pages[0].widgets[0].rules[0].if[1]") for i in issues), issues
    issues = structure_issues(
        project_dict(widgets=[{"id": "w", "type": "text", "rules": [{"kind": "loop"}]}])
    )
    assert issues == ["pages[0].widgets[0].rules[0]: невідомий вид запису: Loop"]


# ------------------------------------------------------------------ display
@pytest.mark.parametrize(
    ("mcu", "pins", "message"),
    [
        ("esp32s3", {"sck": 19}, "pins.sck: GPIO19 зайнятий (USB)"),
        ("esp32s3", {"sck": 49}, "pins.sck: на ESP32-S3 GPIO від 0 до 48"),
        ("esp32", {"sck": 6}, "pins.sck: GPIO6 зайнятий (внутрішній флеш)"),
        ("esp32", {"sck": 34}, "pins.sck: GPIO34 на ESP32 працює лише на вхід"),
        ("esp32c3", {"sck": 12, "mosi": 1, "dc": 2, "cs": 3, "rst": 4, "bl": 5}, "GPIO12 зайнятий (флеш)"),
        ("esp32c3", {"sck": 18, "mosi": 1, "dc": 2, "cs": 3, "rst": 4, "bl": 5}, "GPIO18 зайнятий (USB)"),
        ("esp32c3", {"sck": 22, "mosi": 1, "dc": 2, "cs": 3, "rst": 4, "bl": 5}, "GPIO від 0 до 21"),
    ],
)  # fmt: skip
def test_pins_per_chip(mcu: str, pins: dict[str, int], message: str) -> None:
    default = {"sck": 12, "mosi": 11, "dc": 9, "cs": 10, "rst": 8, "bl": 7}
    if mcu == "esp32":  # the S3 defaults are not valid on a classic ESP32
        default = {"sck": 18, "mosi": 23, "dc": 2, "cs": 5, "rst": 4, "bl": 15}
    issues = check(display={"mcu": mcu, "pins": {**default, **pins}})
    assert len(issues) == 1, issues
    assert issues[0] == f"display.{message}" or message in issues[0]


def test_duplicate_pins_and_missing_backlight() -> None:
    issues = check(
        display={"pins": {"sck": 12, "mosi": 12, "dc": 9, "cs": 10, "rst": 8, "bl": None}}
    )
    assert issues == [
        "display.pins.sck: GPIO12 вже використано для mosi",
        "display.pins.mosi: GPIO12 вже використано для sck",
    ]


def test_display_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check(display={"spi_hz": 80_000_000}) == []
    issues = check(display={"model": "ILI9341"})
    assert issues == [
        "display.model: невідомий дисплей «ILI9341»; "
        "підтримуються: CYD-ILI9341, CYD-ST7789, GC9A01-1.28, GMT020-02-8B, ILI9341-3.2, "
        "ILI9488-3.5, ST7789-3.2"
    ]
    assert check(display={"model": "ILI9488-3.5"}) == []
    assert check(display={"model": "custom", "custom": {"controller": "GC9A01"}}) == [
        "display.custom: 240×320 зі зсувом 0/0 не вміщується в пам'ять GC9A01 (240×240)"
    ]
    assert check(display={"model": "GC9A01-1.28", "driver": "st7789py"}) == [
        "display.driver: драйвер «st7789py» не працює з контролером GC9A01"
    ]

    import espui.core.checks as checks

    monkeypatch.setattr(checks, "driver_supports", lambda driver, chip: False)
    assert check() == ["display.driver: драйвер «builtin» не підтримує ESP32-S3"]


def test_display_structure() -> None:
    issues = structure_issues(
        project_dict(display={"rotation": 4, "driver": "c_module", "mcu": "rp2040"})
    )
    assert "display.rotation: має бути не більше 3" in issues
    assert any(i.startswith("display.driver: допустимі значення") for i in issues)
    assert any(i.startswith("display.mcu: допустимі значення") for i in issues)


def test_display_enums() -> None:
    display = make_project(display={"mcu": "esp32c3", "driver": "st7789py"}).display
    assert display.mcu is Chip.ESP32C3
    assert display.driver is Driver.ST7789PY


# ------------------------------------------------------------------ images
def image(path: str = "/img/logo.bin", **extra: Any) -> dict[str, Any]:
    return {"name": "logo.png", "path": path, "data": "AAAA", "width": 4, "height": 4, **extra}


def test_images() -> None:
    assert (
        check(
            images={"logo": image()},
            widgets=[{"id": "i", "type": "image", "image": {"file": "logo"}}],
        )
        == []
    )
    issues = check(
        images={
            "a": image(),
            "b": image(),
            "c": image("/img/c/"),
            "d": image("/img/d.bin", frames=["AA"]),
            "e": image("/img/e/", frames=["AA"] * 49, delay_ms=100),
        }
    )
    assert issues == [
        "images.b.path: шлях /img/logo.bin вже зайнятий іншою картинкою",
        "images.c.path: статична картинка зберігається у файлі /img/<назва>.bin",
        "images.d.path: анімація зберігається в папці /img/<назва>/",
        "images.d.frames: анімація має щонайменше 2 кадри",
        "images.d.delay_ms: для анімації потрібна затримка між кадрами",
        "images.e.frames: щонайбільше 48 кадрів",
    ]


def test_image_path_and_key_format() -> None:
    issues = structure_issues(project_dict(images={"x": image("logo.png")}))
    assert issues == ["images.x.path: неправильний формат"]
    issues = structure_issues(project_dict(images={"Logo Big": image()}))
    assert issues == ["images.Logo Big: неправильний формат"]


# ------------------------------------------------------------------ error object
def test_validation_error_message() -> None:
    with pytest.raises(ProjectValidationError) as info:
        validate_project(make_project(parameters=[FLAG, FLAG]))
    assert str(info.value) == (
        "Проєкт містить помилки (1):\n  • pages[0].parameters[1].name: параметр «on» вже є"
    )
    assert info.value.issues[0].path == "pages[0].parameters[1].name"


def test_remove_parameter() -> None:
    project = make_project(
        parameters=[TEMP, FLAG],
        widgets=[
            {"id": "a", "type": "value", "bind": "t", "rules": [
                {"if": ["t", ">", 5], "set": "color", "to": "#ff0000"},
                {"if": ["on", "==", True], "set": "visible", "to": False},
                {"param": "t", "prop": "x", "at_min": 0, "at_max": 10},
            ]},
        ],
    )  # fmt: skip
    page = project.pages[0]
    page.test_values = {"t": 7.0, "on": True}
    assert page.remove_parameter("t") == 2
    widget = page.widgets[0]
    assert widget.bind is None
    assert [r.param for r in widget.rules] == ["on"]
    assert page.test_values == {"on": True}
    assert [p.name for p in page.parameters] == ["on"]
    assert check_project(project) == []
    assert page.remove_parameter("ghost") == 0
