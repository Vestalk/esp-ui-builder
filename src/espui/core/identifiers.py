"""Names that end up as Python identifiers in generated code."""

from __future__ import annotations

import keyword
import re

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,31}$")
RESERVED_WORDS = frozenset(keyword.kwlist) | {"self"}
# ui_<page>.py must not collide with the shared files of a generated project.
RESERVED_PAGE_NAMES = frozenset({"display", "st7789", "fonts"})


def identifier_problem(name: str) -> str | None:
    """Ukrainian reason why ``name`` can't be used as a generated identifier, or None."""
    if not name:
        return "назва порожня"
    if not IDENTIFIER_RE.fullmatch(name):
        return "лише латинські малі літери, цифри і _, не з цифри, до 32 символів"
    if name in RESERVED_WORDS:
        return f"«{name}» — зарезервоване слово Python"
    return None


def page_name_problem(name: str) -> str | None:
    problem = identifier_problem(name)
    if problem is None and name in RESERVED_PAGE_NAMES:
        return f"ui_{name}.py вже зайнято спільним файлом"
    return problem
