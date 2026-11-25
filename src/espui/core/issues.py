"""Validation problems with Ukrainian messages and a path to the field."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from espui.i18n import tr

Loc = tuple[str | int, ...]

# Pydantic inserts union tags / validator names into error locations. Our tags
# are Capitalised (models.py) and every user-defined name is lowercase.
_LOC_NOISE_PREFIXES = ("function-", "literal[", "tagged-union[")


def format_path(loc: Iterable[str | int]) -> str:
    """``("pages", 0, "widgets", 2, "x")`` -> ``pages[0].widgets[2].x``."""
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            out += f".{part}" if out else part
    return out


@dataclass(frozen=True, slots=True)
class Issue:
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or tr('(проєкт)')}: {self.message}"


class ProjectError(Exception):
    """Base class: the project can't be opened or saved."""


class ProjectFormatError(ProjectError):
    """Not a JSON project file, or an unsupported version."""


class ProjectValidationError(ProjectError):
    def __init__(self, issues: Sequence[Issue]) -> None:
        self.issues = tuple(issues)
        super().__init__(str(self))

    def __str__(self) -> str:
        head = tr("Проєкт містить помилки ({v1}):").format(v1=len(self.issues))
        return "\n".join([head, *(f"  • {issue}" for issue in self.issues)])


# ------------------------------------------------------------------ pydantic -> Ukrainian
_MESSAGES: dict[str, str] = {
    "missing": tr("обов'язкове поле"),
    "extra_forbidden": tr("невідоме поле"),
    "int_type": tr("очікується ціле число"),
    "int_parsing": tr("очікується ціле число"),
    "int_from_float": tr("очікується ціле число"),
    "float_type": tr("очікується число"),
    "float_parsing": tr("очікується число"),
    "finite_number": tr("очікується скінченне число"),
    "bool_type": tr("очікується true або false"),
    "bool_parsing": tr("очікується true або false"),
    "string_type": tr("очікується рядок"),
    "list_type": tr("очікується список"),
    "tuple_type": tr("очікується список"),
    "dict_type": tr("очікується об'єкт"),
    "model_type": tr("очікується об'єкт"),
    "model_attributes_type": tr("очікується об'єкт"),
    "literal_error": tr("допустимі значення: {expected}"),
    "enum": tr("допустимі значення: {expected}"),
    "greater_than": tr("має бути більше за {gt}"),
    "greater_than_equal": tr("має бути не менше {ge}"),
    "less_than": tr("має бути менше за {lt}"),
    "less_than_equal": tr("має бути не більше {le}"),
    "too_short": tr("щонайменше {min_length} елемент(и)"),
    "too_long": tr("щонайбільше {max_length} елемент(ів)"),
    "string_too_short": tr("щонайменше {min_length} символ(и)"),
    "string_too_long": tr("щонайбільше {max_length} символів"),
    "string_pattern_mismatch": tr("неправильний формат"),
    "union_tag_invalid": tr("невідомий вид запису: {tag}"),
    "union_tag_not_found": tr("не вдалося визначити вид запису"),
    "too_many_items": tr("забагато елементів"),
}


def _message(error: Any) -> str:
    kind = error["type"]
    template = _MESSAGES.get(kind)
    if template is None:
        # Custom errors (PydanticCustomError) already carry a Ukrainian message.
        msg: str = error["msg"]
        return msg.removeprefix("Value error, ")
    ctx = {k: _ctx_value(v) for k, v in (error.get("ctx") or {}).items()}
    try:
        return template.format(**ctx)
    except (KeyError, IndexError):
        return template


def _ctx_value(value: Any) -> str:
    text = str(value)
    return text.replace("'", "«", 1).replace("'", "»", 1) if text.count("'") == 2 else text


# ``parameters`` is discriminated by its ``type`` field: pydantic puts that
# value (lowercase) right after the list index, e.g. ``parameters, 0, "bool"``.
_PARAMETER_TAGS = frozenset({"float", "int", "bool", "str", "enum", "series"})


def _is_noise(part: str | int, kept: Loc) -> bool:
    if not isinstance(part, str):
        return False
    if part[:1].isupper() or part.startswith(_LOC_NOISE_PREFIXES):
        return True
    return (
        part in _PARAMETER_TAGS
        and len(kept) >= 2
        and isinstance(kept[-1], int)
        and kept[-2] == "parameters"
    )


def _clean_loc(loc: Loc) -> Loc:
    kept: Loc = ()
    for i, part in enumerate(loc):
        if part == "[key]":
            continue  # problem with a dict key: the path ends at that key
        is_key = i + 1 < len(loc) and loc[i + 1] == "[key]"
        if is_key or not _is_noise(part, kept):
            kept = (*kept, part)
    return kept


def issues_from_validation_error(error: ValidationError, prefix: Loc = ()) -> list[Issue]:
    seen: set[tuple[str, str]] = set()
    issues: list[Issue] = []
    for item in error.errors(include_url=False):
        issue = Issue(format_path(prefix + _clean_loc(tuple(item["loc"]))), _message(item))
        key = (issue.path, issue.message)
        if key not in seen:  # unions report the same place several times
            seen.add(key)
            issues.append(issue)
    return issues
