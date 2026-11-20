"""Builders for small projects used by the core tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from espui.core.issues import Issue
from espui.core.models import Page, Project

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def project_dict(
    parameters: list[dict[str, Any]] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    page: dict[str, Any] = {
        "name": "main",
        "parameters": parameters or [],
        "widgets": widgets or [],
    }
    return {"schema": 1, "pages": [page], **extra}


def make_project(
    parameters: list[dict[str, Any]] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> Project:
    return Project.model_validate(project_dict(parameters, widgets, **extra))


def make_page(
    parameters: list[dict[str, Any]] | None = None,
    widgets: list[dict[str, Any]] | None = None,
    **extra: Any,
) -> Page:
    return Page.model_validate(
        {"name": "main", "parameters": parameters or [], "widgets": widgets or [], **extra}
    )


def paths(issues: list[Issue]) -> list[str]:
    return [issue.path for issue in issues]


TEMP = {"name": "t", "type": "float", "min": 0, "max": 100, "default": 50}
LEVEL = {"name": "n", "type": "int", "min": 0, "max": 10, "default": 5}
FLAG = {"name": "on", "type": "bool"}
MODE = {"name": "mode", "type": "enum", "values": ["a", "b", "c"]}
NAME = {"name": "label", "type": "str", "max_len": 8, "default": "hi"}
SERIES = {"name": "s", "type": "series", "min": 0, "max": 10, "max_points": 4}


@pytest.fixture
def mockup_path() -> Path:
    return FIXTURES / "mockup_weather.espui.json"
