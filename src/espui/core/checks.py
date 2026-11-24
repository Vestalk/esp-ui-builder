"""Rules that relate fields to each other.

:mod:`espui.core.models` checks single fields; here we check what pydantic
can't see from one field: names are unique, ranges are ordered, bindings and
rules refer to existing parameters of a compatible type, pins suit the chip,
images exist. Every problem is an :class:`Issue` with an exact path, so the
GUI can show it next to the field (and check drafts while editing).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator

from espui.core.compat import (
    can_bind,
    condition_props,
    is_numeric,
    mapping_props,
    operators_for,
    prop_value_problem,
    series_problem,
    value_problem,
)
from espui.core.evaluate import format_problem
from espui.core.hardware import CHIP_RULES, driver_drives, driver_supports
from espui.core.identifiers import identifier_problem
from espui.core.issues import Issue, Loc, ProjectValidationError, format_path
from espui.core.models import (
    FONT_SIZE_TYPES,
    FONT_TYPES,
    MAX_ANIMATION_FRAMES,
    Condition,
    Display,
    EnumParameter,
    FloatParameter,
    ImageAsset,
    IntParameter,
    MappingRule,
    Page,
    Parameter,
    Project,
    SeriesParameter,
    Widget,
)
from espui.displays import CUSTOM_MODEL, UnknownDisplayError

_TYPE_TITLES = {
    "float": "float",
    "int": "int",
    "bool": "bool",
    "str": "str",
    "enum": "enum",
    "series": "series",
}


def _issue(loc: Loc, message: str) -> Issue:
    return Issue(format_path(loc), message)


def _repeats(names: Iterable[str]) -> set[int]:
    """Indices of names already seen earlier (the first occurrence is fine)."""
    seen: set[str] = set()
    out: set[int] = set()
    for i, name in enumerate(names):
        if name in seen:
            out.add(i)
        seen.add(name)
    return out


# ------------------------------------------------------------------ project
def check_project(project: Project) -> list[Issue]:
    """All cross-field problems of a structurally valid project (empty = OK)."""
    issues = list(check_display(project.display, ("display",)))
    issues += check_images(project)
    dup_pages = _repeats(p.name for p in project.pages)
    for i, page in enumerate(project.pages):
        loc: Loc = ("pages", i)
        if i in dup_pages:
            issues.append(_issue((*loc, "name"), f"сторінка «{page.name}» вже є"))
        issues += check_page(page, loc, project)
    return issues


def validate_project(project: Project) -> Project:
    """Raise :class:`ProjectValidationError` if :func:`check_project` finds anything."""
    issues = check_project(project)
    if issues:
        raise ProjectValidationError(issues)
    return project


# ------------------------------------------------------------------ display
def check_display(display: Display, loc: Loc = ("display",)) -> Iterator[Issue]:
    try:
        profile = display.profile
    except UnknownDisplayError as error:
        yield _issue((*loc, "model"), str(error))
        return
    if display.spi_hz > profile.spi_hz.max:
        yield _issue(
            (*loc, "spi_hz"),
            f"максимум {profile.spi_hz.max // 1_000_000} МГц для {profile.model}",
        )
    if not driver_supports(display.driver, display.mcu):
        yield _issue(
            (*loc, "driver"),
            f"драйвер «{display.driver}» не підтримує {display.mcu.label}",
        )
    if not driver_drives(display.driver, profile.controller):
        yield _issue(
            (*loc, "driver"),
            f"драйвер «{display.driver}» не працює з контролером {profile.controller}",
        )
    if display.model == CUSTOM_MODEL:
        ram_w, ram_h = profile.controller_info.ram
        if profile.width + profile.x_offset > ram_w or profile.height + profile.y_offset > ram_h:
            yield _issue(
                (*loc, "custom"),
                f"{profile.width}×{profile.height} зі зсувом {profile.x_offset}/"
                f"{profile.y_offset} не вміщується в пам'ять {profile.controller} "
                f"({ram_w}×{ram_h})",
            )
    rules = CHIP_RULES[display.mcu]
    # Every GPIO of the module: display and touch panel (one pin, one job).
    places: dict[str, Loc] = {n: (*loc, "pins", n) for n in display.pins.assigned()}
    assigned = dict(display.pins.assigned())
    if display.touch is not None:
        for name, gpio in display.touch.assigned().items():
            assigned[name] = gpio
            places[name] = (*loc, "touch", name.removeprefix("touch_"))
    used = Counter(assigned.values())
    for name, gpio in assigned.items():
        problem = rules.problem(gpio, input_only_ok=name in INPUT_PINS)
        if problem:
            yield _issue(places[name], problem)
        elif used[gpio] > 1:
            others = ", ".join(n for n, g in assigned.items() if g == gpio and n != name)
            yield _issue(places[name], f"GPIO{gpio} вже використано для {others}")
    yield from _check_extras(display, loc)


INPUT_PINS = frozenset({"miso", "touch_irq", "touch_miso"})
"""Pins the board only reads: GPIO 34-39 of the ESP32 (input only) are fine for them."""


def _check_extras(display: Display, loc: Loc) -> Iterator[Issue]:
    """What a touch panel on the module needs."""
    touch = display.touch
    if touch is not None and touch.kind == "xpt2046":
        own = [touch.sck, touch.mosi, touch.miso]
        if any(v is not None for v in own) and None in own:
            yield _issue(
                (*loc, "touch", "sck"),
                "окрема шина сенсора: вкажіть усі три піни T_CLK, T_DIN, T_DO (або жодного)",
            )
        elif not touch.own_bus and display.pins.miso is None:
            yield _issue(
                (*loc, "pins", "miso"), "вкажіть MISO: сенсор XPT2046 відповідає платі по ньому"
            )
    if touch is not None:
        if touch.kind == "xpt2046":
            if touch.cs is None:
                yield _issue((*loc, "touch", "cs"), "вкажіть T_CS сенсора")
            if touch.x_min == touch.x_max or touch.y_min == touch.y_max:
                yield _issue((*loc, "touch", "x_max"), "калібрування: краї не можуть збігатися")
        else:
            for name in ("sda", "scl"):
                if getattr(touch, name) is None:
                    yield _issue((*loc, "touch", name), f"вкажіть {name.upper()} сенсора (I2C)")


# ------------------------------------------------------------------ images
def check_images(project: Project) -> Iterator[Issue]:
    taken = _repeats(image.path for image in project.images.values())
    for i, (key, image) in enumerate(project.images.items()):
        loc: Loc = ("images", key)
        if i in taken:
            yield _issue((*loc, "path"), f"шлях {image.path} вже зайнятий іншою картинкою")
        yield from _check_image(image, loc)


def _check_image(image: ImageAsset, loc: Loc) -> Iterator[Issue]:
    is_folder = image.path.endswith("/")
    if image.is_animation:
        if not is_folder:
            yield _issue((*loc, "path"), "анімація зберігається в папці /img/<назва>/")
        frames = image.frames or []
        if len(frames) < 2:
            yield _issue((*loc, "frames"), "анімація має щонайменше 2 кадри")
        if len(frames) > MAX_ANIMATION_FRAMES:
            yield _issue((*loc, "frames"), f"щонайбільше {MAX_ANIMATION_FRAMES} кадрів")
        if image.delay_ms is None:
            yield _issue((*loc, "delay_ms"), "для анімації потрібна затримка між кадрами")
    elif is_folder:
        yield _issue((*loc, "path"), "статична картинка зберігається у файлі /img/<назва>.bin")


# ------------------------------------------------------------------ page
def check_page(page: Page, loc: Loc, project: Project | None = None) -> list[Issue]:
    issues: list[Issue] = []
    dup_params = _repeats(p.name for p in page.parameters)
    for i, param in enumerate(page.parameters):
        p_loc: Loc = (*loc, "parameters", i)
        if i in dup_params:
            issues.append(_issue((*p_loc, "name"), f"параметр «{param.name}» вже є"))
        issues += check_parameter(param, p_loc)

    for name, value in page.test_values.items():
        v_loc: Loc = (*loc, "test_values", name)
        target = page.parameter(name)
        if target is None:
            issues.append(_issue(v_loc, f"немає параметра «{name}»"))
        elif problem := value_problem(target, value):
            issues.append(_issue(v_loc, problem))

    dup_ids = _repeats(w.id for w in page.widgets)
    for i, widget in enumerate(page.widgets):
        w_loc: Loc = (*loc, "widgets", i)
        if i in dup_ids:
            issues.append(_issue((*w_loc, "id"), f"елемент «{widget.id}» вже є"))
        issues += check_widget(widget, page, w_loc, project)
    return issues


# ------------------------------------------------------------------ parameters
def check_parameter(param: Parameter, loc: Loc) -> list[Issue]:
    issues: list[Issue] = []
    ranged = isinstance(param, FloatParameter | IntParameter | SeriesParameter)
    if ranged and not param.min < param.max:  # type: ignore[union-attr]
        issues.append(_issue((*loc, "max"), "max має бути більше за min"))
        return issues  # the default can't be checked against a broken range
    if isinstance(param, EnumParameter):
        dup = sorted({param.values[i] for i in _repeats(param.values)})
        if dup:
            issues.append(_issue((*loc, "values"), f"варіанти повторюються: {', '.join(dup)}"))
        if any(not v for v in param.values):
            issues.append(_issue((*loc, "values"), "порожній варіант"))
    if isinstance(param, SeriesParameter):
        problem = series_problem(param, param.default)
    else:
        problem = value_problem(param, param.default)
    if problem:
        issues.append(_issue((*loc, "default"), problem))
    return issues


# ------------------------------------------------------------------ widgets
def check_widget(
    widget: Widget, page: Page, loc: Loc, project: Project | None = None
) -> list[Issue]:
    issues: list[Issue] = []
    kind = widget.type
    if widget.font is not None and kind not in FONT_TYPES:
        issues.append(_issue((*loc, "font"), f"шрифт не застосовується до «{kind}»"))
    if widget.font_size is not None and kind not in FONT_SIZE_TYPES:
        issues.append(_issue((*loc, "font_size"), f"розмір шрифту не застосовується до «{kind}»"))
    if kind == "chart" and widget.rotation_deg:
        issues.append(_issue((*loc, "rotation_deg"), "графік не повертається"))
    # Only a bound text is a printf format; an unbound one is shown as is (as in the mock-up).
    bound = widget.bind is not None
    if kind in ("text", "value") and bound and (problem := format_problem(widget.format)):
        issues.append(_issue((*loc, "format"), problem))
    if kind == "line" and widget.w == 0 and widget.h == 0:
        issues.append(_issue((*loc, "w"), "лінія нульової довжини"))

    if widget.bind:
        param = page.parameter(widget.bind)
        if param is None:
            issues.append(_issue((*loc, "bind"), f"немає параметра «{widget.bind}»"))
        elif not can_bind(kind, param):
            issues.append(
                _issue(
                    (*loc, "bind"),
                    f"до «{kind}» не можна прив'язати параметр типу {_TYPE_TITLES[param.type]}",
                )
            )

    image_file = widget.image.file if kind == "image" and widget.image else None
    if image_file and project is not None and image_file not in project.images:
        issues.append(_issue((*loc, "image", "file"), f"немає картинки «{image_file}»"))
    if kind == "chart" and widget.chart:
        lo, hi = widget.chart.y_min, widget.chart.y_max
        if lo is not None and hi is not None and not lo < hi:
            issues.append(_issue((*loc, "chart", "y_max"), "y_max має бути більше за y_min"))

    if widget.on_tap is not None and (problem := identifier_problem(widget.on_tap)):
        issues.append(_issue((*loc, "on_tap"), f"«{widget.on_tap}»: {problem}"))
    for i, rule in enumerate(widget.rules):
        r_loc: Loc = (*loc, "rules", i)
        if isinstance(rule, Condition):
            issues += _check_condition(rule, widget, page, r_loc)
        else:
            issues += _check_mapping(rule, widget, page, r_loc)
    return issues


def _check_condition(rule: Condition, widget: Widget, page: Page, loc: Loc) -> list[Issue]:
    issues: list[Issue] = []
    param = page.parameter(rule.param)
    if param is None:
        issues.append(_issue((*loc, "if", 0), f"немає параметра «{rule.param}»"))
    else:
        ops = operators_for(param)
        if not ops:
            issues.append(_issue((*loc, "if", 0), "умова не може залежати від series"))
        elif rule.op not in ops:
            issues.append(_issue((*loc, "if", 1), f"для {param.type} можна лише: {', '.join(ops)}"))
        elif problem := _compare_value_problem(param, rule.value):
            issues.append(_issue((*loc, "if", 2), problem))
    if rule.prop not in condition_props(widget.type):
        issues.append(_issue((*loc, "set"), f"«{rule.prop}» не змінюється для «{widget.type}»"))
    elif problem := prop_value_problem(rule.prop, rule.to):
        issues.append(_issue((*loc, "to"), problem))
    return issues


def _compare_value_problem(param: Parameter, value: object) -> str | None:
    """Like :func:`value_problem`, but numbers outside the range are allowed (``t > 100``)."""
    if isinstance(value, tuple):  # in / not in: [from, to]
        lo, hi = value
        if any(isinstance(v, bool) for v in value):
            return "очікуються числа"
        if lo > hi:
            return f"діапазон: «від» ({lo:g}) більше за «до» ({hi:g})"
        return None
    if isinstance(param, FloatParameter | IntParameter):
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "очікується число"
        return None
    return value_problem(param, value)


def _check_mapping(rule: MappingRule, widget: Widget, page: Page, loc: Loc) -> list[Issue]:
    issues: list[Issue] = []
    param = page.parameter(rule.param)
    if param is None:
        issues.append(_issue((*loc, "param"), f"немає параметра «{rule.param}»"))
    elif not is_numeric(param):
        issues.append(_issue((*loc, "param"), "залежність можлива лише від float або int"))
    if rule.prop not in mapping_props(widget.type):
        issues.append(_issue((*loc, "prop"), f"«{rule.prop}» не змінюється для «{widget.type}»"))
    elif rule.prop == "opacity":
        for field in ("at_min", "at_max"):
            if not 0 <= getattr(rule, field) <= 100:
                issues.append(_issue((*loc, field), "непрозорість від 0 до 100 %"))
    return issues
