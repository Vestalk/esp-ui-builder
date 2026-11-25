"""Bring any supported project dict to the current ``.espui`` layout.

Two sources:

* ``.espui`` files of older ``schema`` versions (and current ones with legacy
  widget fields such as ``show`` or "opacity from a parameter");
* sessions exported from the HTML mock-up (``docs/plan.html`` → Файл →
  Експорт, ``*.espui.json``): short field names (``W``/``P``/``V``, ``col``,
  ``fs``, ``alpha``, ...), pins named after the module's silk-screen, images
  as data URLs.

Everything here works on plain dicts *before* pydantic validation. Unknown
fields are left in place, so they survive a load/save round trip.
"""

from __future__ import annotations

import base64
import copy
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote_to_bytes

from espui.core.issues import ProjectFormatError
from espui.core.models import SCHEMA_VERSION
from espui.i18n import tr

Data = dict[str, Any]

# Legacy widget fields replaced by ``rules[]`` (same names in the mock-up and
# in early ``.espui`` drafts).
_LEGACY_FIELDS = (
    "show",
    "omode",
    "opp",
    "o0",
    "o1",
    "mxp",
    "myp",
    "x0",
    "x1",
    "y0",
    "y1",
    "rmode",
    "rp",
    "a0",
    "a1",
)


# ------------------------------------------------------------------ entry point
def is_mockup(data: Data) -> bool:
    pages = data.get("pages")
    return (
        isinstance(pages, list)
        and bool(pages)
        and all(isinstance(p, dict) and "W" in p and "P" in p for p in pages)
    )


def migrate(source: Any) -> Data:
    """Return a migrated deep copy of ``source`` in the current schema layout."""
    if not isinstance(source, dict):
        raise ProjectFormatError(
            tr("Файл не схожий на проєкт ESP UI Builder: очікується об'єкт JSON")
        )
    data: Data = copy.deepcopy(source)
    if is_mockup(data):
        data = from_mockup(data)
    version = data.get("schema", SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise ProjectFormatError(tr("Невідома версія формату: {version!r}").format(version=version))
    if version > SCHEMA_VERSION:
        raise ProjectFormatError(
            tr(
                "Файл створено новішою версією програми (формат {version}, "
                "підтримується до {SCHEMA_VERSION}). Оновіть ESP UI Builder."
            ).format(version=version, SCHEMA_VERSION=SCHEMA_VERSION)
        )
    for step in range(version, SCHEMA_VERSION):
        data = _STEPS[step](data)
    data["schema"] = SCHEMA_VERSION
    for page in data.get("pages") or []:
        if not isinstance(page, dict):
            continue
        params = {p.get("name"): p for p in page.get("parameters") or [] if isinstance(p, dict)}
        for widget in page.get("widgets") or []:
            if isinstance(widget, dict):
                migrate_legacy_widget(widget, params)
    return data


# Schema version N -> N+1. Empty while the format is at version 1.
_STEPS: dict[int, Callable[[Data], Data]] = {}


# ------------------------------------------------------------------ legacy widget fields
def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return int(number) if number.is_integer() else number


def migrate_legacy_widget(widget: Data, params: dict[Any, Data]) -> Data:
    """Move ``show`` / opacity / position / angle "from a parameter" into ``rules[]``.

    Mirrors ``migrate()`` of the mock-up, so both open old files the same way.
    """
    if not any(key in widget for key in _LEGACY_FIELDS):
        return widget
    rules = widget.setdefault("rules", [])
    if not isinstance(rules, list):
        return widget

    show = widget.get("show")
    if isinstance(show, dict) and show.get("param"):
        # "visible when param == when" -> "hidden when param == not when".
        rules.insert(
            0,
            {
                "kind": "condition",
                "if": [show["param"], "==", not show.get("when", True)],
                "set": "visible",
                "to": False,
            },
        )

    mode = widget.get("omode")
    if mode == "static":
        widget.setdefault("opacity", 100)
    elif mode == "param" and widget.get("opp"):
        param_name = widget["opp"]
        a0, a1 = _num(widget.get("o0"), 0), _num(widget.get("o1"), 100)
        if (params.get(param_name) or {}).get("type") == "bool":
            for value, to in ((False, a0), (True, a1)):
                rules.append(
                    {
                        "kind": "condition",
                        "if": [param_name, "==", value],
                        "set": "opacity",
                        "to": to,
                    }
                )
        else:
            rules.append(
                {
                    "kind": "mapping",
                    "param": param_name,
                    "prop": "opacity",
                    "at_min": a0,
                    "at_max": a1,
                }
            )
        widget["opacity"] = 100
    elif mode == "none":
        widget["opacity"] = 100

    for axis in ("x", "y"):
        param_name = widget.get(f"m{axis}p")
        if param_name:
            rules.append(
                {
                    "kind": "mapping",
                    "param": param_name,
                    "prop": axis,
                    "at_min": _num(widget.get(f"{axis}0")),
                    "at_max": _num(widget.get(f"{axis}1")),
                }
            )

    rmode = widget.get("rmode")
    if rmode == "param" and widget.get("rp"):
        rules.append(
            {
                "kind": "mapping",
                "param": widget["rp"],
                "prop": "angle",
                "at_min": _num(widget.get("a0")),
                "at_max": _num(widget.get("a1"), 360),
            }
        )
        widget["rotation_deg"] = 0
    elif rmode == "none":
        widget["rotation_deg"] = 0

    for key in _LEGACY_FIELDS:
        widget.pop(key, None)
    return widget


# ------------------------------------------------------------------ mock-up export
_PIN_NAMES = {"SCL": "sck", "SDA": "mosi", "RES": "rst", "DC": "dc", "CS": "cs", "BLK": "bl"}
_PARAM_TYPES = {"int32": "int", "string": "str"}
_RULE_PROPS = {"col": "color", "alpha": "opacity"}
_PIVOTS = {
    "c": "center",
    "tl": "top_left",
    "t": "top",
    "tr": "top_right",
    "l": "left",
    "r": "right",
    "bl": "bottom_left",
    "b": "bottom",
    "br": "bottom_right",
}
_SHAPES = frozenset({"rect", "circle", "line", "image", "chart"})


def _rename(data: Data, names: dict[str, str]) -> Data:
    for old, new in names.items():
        if old in data:
            data[new] = data.pop(old)
    return data


def from_mockup(data: Data) -> Data:
    data.pop("format", None)
    data.pop("v", None)
    images, image_keys = _mockup_images(data.pop("images", None) or {})
    project: Data = {"schema": 1}
    if isinstance(data.get("display"), dict):
        project["display"] = _mockup_display(data.pop("display"))
    editor: Data = {}
    if "zoom" in data:
        editor["zoom"] = data.pop("zoom")
    if "pi" in data:
        editor["page"] = data.pop("pi")
    project["pages"] = [_mockup_page(p, image_keys) for p in data.pop("pages")]
    project["images"] = images
    if editor:
        project["editor"] = editor
    project.update(data)  # anything unknown is kept
    return project


def _mockup_display(display: Data) -> Data:
    _rename(display, {"rot": "rotation", "drv": "driver"})
    if "freq" in display:
        display["spi_hz"] = int(_num(display.pop("freq")) * 1_000_000)
    pins = display.get("pins")
    if isinstance(pins, dict):
        display["pins"] = {
            _PIN_NAMES.get(k, k): (None if v in ("", None) else v) for k, v in pins.items()
        }
    return display


def _mockup_page(page: Data, image_keys: dict[str, str]) -> Data:
    params = [_mockup_parameter(p) if isinstance(p, dict) else p for p in page.pop("P") or []]
    by_name = {p.get("name"): p for p in params if isinstance(p, dict)}
    out: Data = {"name": page.pop("name", "")}
    if "bg" in page:
        out["background"] = page.pop("bg")
    out["parameters"] = params
    out["widgets"] = [
        _mockup_widget(w, by_name, image_keys) if isinstance(w, dict) else w
        for w in page.pop("W") or []
    ]
    values = page.pop("V", None) or {}
    defaults = {p.get("name"): p.get("default") for p in params if isinstance(p, dict)}
    # The mock-up stores every value; keep only the ones that differ from defaults.
    out["test_values"] = {k: v for k, v in values.items() if k in defaults and v != defaults[k]}
    out.update(page)
    return out


def _mockup_parameter(param: Data) -> Data:
    _rename(param, {"def": "default", "vals": "values", "size": "max_len", "n": "max_points"})
    param["type"] = _PARAM_TYPES.get(param.get("type", ""), param.get("type"))
    if "xk" in param:
        param["x_kind"] = "label" if param.pop("xk") == "str" else "number"
    return param


def _mockup_widget(widget: Data, params: dict[Any, Data], image_keys: dict[str, str]) -> Data:
    _rename(
        widget,
        {
            "col": "color",
            "fs": "font_size",
            "fmt": "format",
            "op": "opacity",
            "rot": "rotation_deg",
        },
    )
    kind = widget.get("type")
    for axis in ("x", "y", "w", "h"):
        if isinstance(widget.get(axis), float):
            widget[axis] = round(widget[axis])
    if kind in _SHAPES or not widget.get("font_size"):
        widget.pop("font_size", None)
    if kind in _SHAPES - {"chart"}:
        widget.pop("font", None)
    if widget.get("bind") == "":
        widget["bind"] = None

    pivot = widget.pop("pvp", None)
    pvx, pvy = widget.pop("pvx", None), widget.pop("pvy", None)
    if pivot == "custom":
        widget["pivot"] = {"x": _num(pvx), "y": _num(pvy)}
    elif pivot in _PIVOTS:
        widget["pivot"] = _PIVOTS[pivot]

    image: Data = {k: widget.pop(k) for k in ("img", "fit", "play") if k in widget}
    if kind == "image":
        file = image.pop("img", "") or None
        widget["image"] = {"file": image_keys.get(file, file) if file else None, **image}

    chart_keys = ("xl", "yl", "ymin", "ymax", "style", "grid")
    chart: Data = {k: widget.pop(k) for k in chart_keys if k in widget}
    if kind == "chart":
        _rename(chart, {"xl": "axis_x", "yl": "axis_y", "ymin": "y_min", "ymax": "y_max"})
        for key in ("y_min", "y_max"):
            if chart.get(key) in ("", None):
                chart[key] = None
            else:
                chart[key] = _num(chart[key])
        widget["chart"] = chart

    migrate_legacy_widget(widget, params)
    widget["rules"] = [_mockup_rule(r, params) for r in widget.get("rules") or []]
    return widget


def _mockup_rule(rule: Any, params: dict[Any, Data]) -> Any:
    if not isinstance(rule, dict) or rule.get("kind") in ("condition", "mapping"):
        return rule  # already converted (legacy migration) or not a rule at all
    kind = rule.pop("kind", "if")
    prop = rule.get("prop")
    prop = _RULE_PROPS.get(prop, prop) if isinstance(prop, str) else prop
    if kind == "map":
        out: Data = {
            "kind": "mapping",
            "param": rule.pop("param", ""),
            "prop": prop,
            "at_min": _num(rule.pop("a", 0)),
            "at_max": _num(rule.pop("b", 0)),
        }
    else:
        param = rule.pop("param", "")
        value = rule.pop("val", None)
        if (params.get(param) or {}).get("type") in ("float", "int") and isinstance(value, str):
            value = _num(value, value)  # type: ignore[arg-type]
        out = {
            "kind": "condition",
            "if": [param, rule.pop("op", "=="), value],
            "set": prop,
            "to": _mockup_rule_value(prop, rule.pop("to", None)),
        }
    rule.pop("prop", None)
    out.update(rule)
    return out


def _mockup_rule_value(prop: Any, value: Any) -> Any:
    if prop == "visible":
        return value not in ("0", 0, False, "false", None, "")
    if prop in ("opacity", "angle", "x", "y"):
        return _num(value)
    return value


# ------------------------------------------------------------------ images
_DATA_URL_RE = re.compile(
    r"^data:(?P<mime>[\w/+.-]+)?(?P<b64>;base64)?,(?P<payload>.*)$", re.DOTALL
)
_KEY_RE = re.compile(r"[^a-z0-9_-]+")


def parse_data_url(url: str) -> tuple[str, str]:
    """``data:`` URL -> (mime, base64 payload). Percent-encoded payloads are re-encoded."""
    match = _DATA_URL_RE.match(url)
    if match is None:
        raise ProjectFormatError(tr("картинка має бути data: URL"))
    mime = match["mime"] or "application/octet-stream"
    payload = match["payload"]
    if match["b64"]:
        return mime, payload
    return mime, base64.b64encode(unquote_to_bytes(payload)).decode("ascii")


def _image_key(path: str) -> str:
    stem = path.rstrip("/").rsplit("/", 1)[-1].removesuffix(".bin")
    return _KEY_RE.sub("_", stem.lower()).strip("_") or "image"


def _mockup_images(images: Data) -> tuple[Data, dict[str, str]]:
    """Mock-up images are keyed by board path; ``.espui`` keys them by a short name."""
    out: Data = {}
    keys: dict[str, str] = {}
    for path, image in images.items():
        if not isinstance(image, dict) or not isinstance(image.get("url"), str):
            continue
        key = base = _image_key(path)
        n = 2
        while key in out:
            key, n = f"{base}_{n}", n + 1
        mime, data = parse_data_url(image["url"])
        asset: Data = {
            "name": image.get("name") or key,
            "path": path,
            "mime": mime,
            "data": data,
            "width": int(_num(image.get("nw"), 64)),
            "height": int(_num(image.get("nh"), 64)),
        }
        frames = image.get("frames")
        if isinstance(frames, list) and frames:
            asset["frames"] = [parse_data_url(f)[1] for f in frames if isinstance(f, str)]
            asset["delay_ms"] = int(_num(image.get("delay"), 100))
        out[key] = asset
        keys[path] = key
    return out, keys
