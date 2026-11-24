"""Loading, saving, migration and the JSON schema."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from espui.core import serializer
from espui.core.issues import ProjectFormatError, ProjectValidationError
from espui.core.migrate import migrate, migrate_legacy_widget, parse_data_url
from espui.core.models import SCHEMA_VERSION, Condition, MappingRule
from tests.unit.core.conftest import FLAG, TEMP, project_dict

ROOT = Path(__file__).resolve().parents[3]


# ------------------------------------------------------------------ mock-up export
def test_mockup_export_opens_validates_and_round_trips(mockup_path: Path, tmp_path: Path) -> None:
    project = serializer.load(mockup_path)
    assert [p.name for p in project.pages] == ["main", "settings"]
    assert project.display.rotation == 1
    assert project.display.spi_hz == 40_000_000
    assert project.display.pins.assigned() == {
        "sck": 12,
        "mosi": 11,
        "dc": 9,
        "cs": 10,
        "rst": 8,
        "bl": 7,
    }

    saved = serializer.save(project, tmp_path / "weather")
    assert saved.name == "weather.espui"
    again = serializer.load(saved)
    assert again == project
    assert serializer.dumps(again) == serializer.dumps(project) == saved.read_text("utf-8")


def test_mockup_parameters_and_values(mockup_path: Path) -> None:
    page = serializer.load(mockup_path).pages[0]
    kinds = {p.name: p.type for p in page.parameters}
    assert kinds == {
        "temperature": "float",
        "humidity": "int",
        "status": "enum",
        "alarm": "bool",
        "weather_icon": "str",
        "temp_day": "series",
    }
    series = page.parameter("temp_day")
    assert series is not None
    assert series.type == "series"
    assert (series.max_points, series.x_kind, len(series.default)) == (24, "number", 8)
    icon = page.parameter("weather_icon")
    assert icon is not None
    assert icon.type == "str"
    assert icon.max_len == 32
    # Only values that differ from defaults are kept as test values.
    assert page.test_values == {"temperature": 31.2, "status": "Увага"}


def test_mockup_range_conditions_open_in_the_program(mockup_path: Path, tmp_path: Path) -> None:
    """docs/plan.html stores a range as op "in" / "not in" and val [from, to]."""
    data = json.loads(mockup_path.read_text("utf-8"))
    page = data["pages"][0]
    needle = next(w for w in page["W"] if w["id"] == "needle")
    needle["rules"] = [
        {"kind": "if", "param": "temperature", "op": "in", "val": [18, 25.5], "prop": "col",
         "to": "#ff0000"},
        {"kind": "if", "param": "temperature", "op": "not in", "val": [0, 30], "prop": "visible",
         "to": "0"},
    ]  # fmt: skip
    path = tmp_path / "ranges.espui.json"
    path.write_text(json.dumps(data, ensure_ascii=False), "utf-8")
    widget = {w.id: w for w in serializer.load(path).pages[0].widgets}["needle"]
    assert [(c.when, c.prop, c.to) for c in widget.conditions()] == [
        (("temperature", "in", (18, 25.5)), "color", "#ff0000"),
        (("temperature", "not in", (0, 30)), "visible", False),
    ]


def test_mockup_widgets_and_rules(mockup_path: Path) -> None:
    page = serializer.load(mockup_path).pages[0]
    by_id = {w.id: w for w in page.widgets}

    title = by_id["title"]
    assert (title.color, title.font_size, title.format, title.bind) == (
        "#9fe1cb",
        14,
        "Погода · Київ",
        None,
    )
    dot = by_id["st_dot"]
    assert dot.font is None
    assert dot.font_size is None
    assert [(r.param, r.op, r.value, r.prop, r.to) for r in dot.conditions()] == [
        ("status", "==", "Увага", "color", "#efa627"),
        ("status", "==", "Помилка", "color", "#e8251a"),
    ]
    (hidden,) = by_id["alarm_lbl"].conditions()
    assert (hidden.value, hidden.prop, hidden.to) == (False, "visible", False)

    needle = by_id["needle"]
    mapping, condition = needle.rules
    assert isinstance(mapping, MappingRule)
    assert (mapping.prop, mapping.at_min, mapping.at_max) == ("angle", -90, 90)
    assert isinstance(condition, Condition)
    assert (condition.op, condition.prop, condition.to) == (">=", "opacity", 50)
    assert needle.pivot.model_dump() == {"x": 0, "y": 0}  # type: ignore[union-attr]

    chart = by_id["t_chart"].chart
    assert chart is not None
    assert (chart.axis_x, chart.axis_y, chart.y_min, chart.y_max) == ("год", "°C", None, None)
    logo = by_id["logo"].image
    assert logo is not None
    assert (logo.file, logo.fit) == ("logo", "cover")


def test_mockup_images(mockup_path: Path) -> None:
    images = serializer.load(mockup_path).images
    assert set(images) == {"logo", "spin"}
    logo, spin = images["logo"], images["spin"]
    assert (logo.path, logo.mime, logo.width, logo.height) == ("/img/logo.bin", "image/png", 4, 2)
    assert base64.b64decode(logo.data).startswith(b"\x89PNG")
    assert not logo.is_animation
    assert spin.is_animation
    assert spin.frames is not None
    assert (spin.path, len(spin.frames), spin.delay_ms) == ("/img/spin/", 2, 120)


def test_mockup_editor_state(mockup_path: Path) -> None:
    assert serializer.load(mockup_path).editor.model_dump() == {"zoom": 1.5, "page": 0}


def test_mockup_minimal_session() -> None:
    data = {
        "pages": [
            {
                "name": "main",
                "P": [{"name": "t", "type": "float", "min": 0, "max": 9, "def": 1}],
                "W": [
                    {"id": "a", "type": "text", "x": 1.6, "fs": 0, "rules": [{"param": "t", "op": ">", "val": "5", "prop": "x", "to": "7"}]},
                    {"id": "b", "type": "chart", "ymin": "2", "ymax": 8},
                    "junk",
                ],
            }
        ],
        "display": {"pins": {"SCL": 12, "BLK": ""}},
        "images": {"/img/x.bin": "junk", "/img/Big Logo.bin": {"url": "data:image/svg+xml,%3Csvg%2F%3E"}, "/img/big-logo.bin": {"url": "data:,x"}},
        "custom": {"keep": True},
    }  # fmt: skip
    out = migrate(data)
    assert out["custom"] == {"keep": True}
    assert out["display"]["pins"] == {"sck": 12, "bl": None}
    a, b, junk = out["pages"][0]["widgets"]
    assert (a["x"], "font_size" in a) == (2, False)
    assert a["rules"] == [{"kind": "condition", "if": ["t", ">", 5], "set": "x", "to": 7}]
    assert (b["chart"]["y_min"], b["chart"]["y_max"]) == (2, 8)
    assert junk == "junk"
    images = out["images"]
    assert set(images) == {"big_logo", "big-logo"}
    assert base64.b64decode(images["big_logo"]["data"]) == b"<svg/>"
    assert images["big_logo"]["mime"] == "image/svg+xml"
    assert images["big-logo"]["mime"] == "application/octet-stream"


def test_mockup_image_key_collision() -> None:
    images = {"/img/a.bin": {"url": "data:,1"}, "/img/a/": {"url": "data:,2"}}
    out = migrate({"pages": [{"name": "main", "P": [], "W": []}], "images": images})
    assert {k: v["path"] for k, v in out["images"].items()} == {"a": "/img/a.bin", "a_2": "/img/a/"}


def test_bad_data_url() -> None:
    with pytest.raises(ProjectFormatError, match="data: URL"):
        parse_data_url("https://example.com/a.png")


# ------------------------------------------------------------------ legacy fields
def legacy(widget: dict[str, Any], params: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    data = project_dict(params or [TEMP, FLAG], [{"id": "w", "type": "text", **widget}])
    result: dict[str, Any] = migrate(data)["pages"][0]["widgets"][0]
    return result


def test_legacy_show() -> None:
    w = legacy(
        {
            "show": {"param": "on", "when": True},
            "rules": [{"if": ["t", ">", 1], "set": "x", "to": 1}],
        }
    )
    assert w["rules"][0] == {
        "kind": "condition",
        "if": ["on", "==", False],
        "set": "visible",
        "to": False,
    }
    assert len(w["rules"]) == 2
    assert "show" not in w


def test_legacy_opacity_from_numeric_param() -> None:
    w = legacy({"omode": "param", "opp": "t", "o0": "10", "o1": 90, "opacity": 40})
    assert w["rules"] == [
        {"kind": "mapping", "param": "t", "prop": "opacity", "at_min": 10, "at_max": 90}
    ]
    assert w["opacity"] == 100


def test_legacy_opacity_from_bool_param() -> None:
    w = legacy({"omode": "param", "opp": "on"})
    assert w["rules"] == [
        {"kind": "condition", "if": ["on", "==", False], "set": "opacity", "to": 0},
        {"kind": "condition", "if": ["on", "==", True], "set": "opacity", "to": 100},
    ]


@pytest.mark.parametrize(("mode", "opacity"), [("static", 30), ("none", 100)])
def test_legacy_opacity_modes(mode: str, opacity: int) -> None:
    w = legacy({"omode": mode, "opacity": 30})
    assert (w["opacity"], w["rules"]) == (opacity, [])


def test_legacy_position_and_angle() -> None:
    w = legacy(
        {
            "mxp": "t",
            "x0": 0,
            "x1": 200,
            "myp": "t",
            "y0": "x",
            "y1": 50.5,
            "rmode": "param",
            "rp": "t",
            "rotation_deg": 30,
        }
    )
    assert w["rules"] == [
        {"kind": "mapping", "param": "t", "prop": "x", "at_min": 0, "at_max": 200},
        {"kind": "mapping", "param": "t", "prop": "y", "at_min": 0, "at_max": 50.5},
        {"kind": "mapping", "param": "t", "prop": "angle", "at_min": 0, "at_max": 360},
    ]
    assert w["rotation_deg"] == 0
    assert not {"mxp", "x0", "rmode", "rp"} & set(w)


def test_legacy_rotation_none() -> None:
    assert legacy({"rmode": "none", "rotation_deg": 30})["rotation_deg"] == 0


def test_legacy_widget_without_legacy_fields_is_untouched() -> None:
    widget = {"id": "w", "rules": "broken", "show": {"param": "on"}}
    assert migrate_legacy_widget({"id": "w"}, {}) == {"id": "w"}
    assert migrate_legacy_widget(widget, {}) == widget


def test_legacy_project_validates() -> None:
    data = project_dict(
        [TEMP, FLAG],
        [
            {
                "id": "w",
                "type": "text",
                "show": {"param": "on", "when": True},
                "mxp": "t",
                "x0": 0,
                "x1": 100,
            }
        ],
    )
    project = serializer.from_dict(data)
    assert len(project.pages[0].widgets[0].rules) == 2


# ------------------------------------------------------------------ versions & errors
def test_unknown_fields_survive(tmp_path: Path) -> None:
    data = project_dict([TEMP], [{"id": "w", "type": "text", "note": "моє"}], plugin={"a": 1})
    data["pages"][0]["author"] = "я"
    text = serializer.dumps(serializer.from_dict(data))
    out = json.loads(text)
    assert out["plugin"] == {"a": 1}
    assert out["pages"][0]["author"] == "я"
    assert out["pages"][0]["widgets"][0]["note"] == "моє"
    assert "моє" in text  # written as UTF-8, not \\u escapes


def test_missing_schema_means_current() -> None:
    assert serializer.from_dict({"pages": [{"name": "main"}]}).schema_version == SCHEMA_VERSION


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "очікується об'єкт JSON"),
        ({"schema": 99, "pages": []}, "новішою версією програми"),
        ({"schema": "1", "pages": []}, "Невідома версія формату"),
        ({"schema": 0, "pages": []}, "Невідома версія формату"),
    ],
)
def test_format_errors(data: Any, message: str) -> None:
    with pytest.raises(ProjectFormatError, match=message):
        serializer.from_dict(data)


def test_structure_error_has_paths() -> None:
    with pytest.raises(ProjectValidationError) as info:
        serializer.loads(
            json.dumps(
                {"pages": [{"name": "main", "widgets": [{"id": "a", "type": "rect", "x": "left"}]}]}
            )
        )
    assert [str(i) for i in info.value.issues] == ["pages[0].widgets[0].x: очікується ціле число"]


def test_check_false_allows_drafts(tmp_path: Path) -> None:
    draft = serializer.from_dict(project_dict([FLAG, FLAG]), check=False)
    with pytest.raises(ProjectValidationError):
        serializer.save(draft, tmp_path / "d.espui")
    path = serializer.save(draft, tmp_path / "d.espui", check=False)
    with pytest.raises(ProjectValidationError):
        serializer.load(path)
    assert len(serializer.load(path, check=False).pages[0].parameters) == 2


def test_load_errors(tmp_path: Path) -> None:
    with pytest.raises(ProjectFormatError, match=r"очікується файл \*\.espui або \*\.espui\.json"):
        serializer.load(tmp_path / "x.txt")
    with pytest.raises(ProjectFormatError, match="не знайдено"):
        serializer.load(tmp_path / "x.espui")
    (tmp_path / "bin.espui").write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ProjectFormatError, match="не є текстовим файлом UTF-8"):
        serializer.load(tmp_path / "bin.espui")
    (tmp_path / "bad.espui").write_text("{oops", encoding="utf-8")
    with pytest.raises(ProjectFormatError, match="рядок 1, стовпець 2"):
        serializer.load(tmp_path / "bad.espui")


def test_load_accepts_bom_and_both_extensions(tmp_path: Path) -> None:
    text = json.dumps({"pages": [{"name": "main"}]})
    for name in ("a.espui", "b.ESPUI.JSON"):
        (tmp_path / name).write_text("﻿" + text, encoding="utf-8")
        assert serializer.load(tmp_path / name).pages[0].name == "main"


def test_save_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = serializer.from_dict({"pages": [{"name": "main"}]})
    target = tmp_path / "sub" / "p.espui"
    serializer.save(project, target)
    before = target.read_text("utf-8")

    def boom(*_: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("os.replace", boom)
    project.pages[0].background = "#ffffff"
    with pytest.raises(OSError, match="disk full"):
        serializer.save(project, target)
    assert target.read_text("utf-8") == before
    assert [p.name for p in target.parent.iterdir()] == ["p.espui"]


# ------------------------------------------------------------------ schema
def test_schema_file_is_up_to_date() -> None:
    committed = (ROOT / "docs" / "espui.schema.json").read_text("utf-8")
    assert committed == serializer.schema_text(), "run: python tools/gen_schema.py"


def test_schema_describes_aliases() -> None:
    schema = serializer.json_schema()
    assert schema["$schema"].endswith("2020-12/schema")
    assert "schema" in schema["properties"]
    assert {"if", "set", "to"} <= set(schema["$defs"]["Condition"]["properties"])


def test_gen_schema_check(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "gen_schema.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
