"""Reading and writing ``.espui`` project files.

``load()`` accepts ``*.espui`` and ``*.espui.json`` (mock-up export), migrates
old layouts (:mod:`espui.core.migrate`), validates the structure (pydantic)
and the relations between fields (:mod:`espui.core.checks`). Errors carry
Ukrainian messages with a path to the field.

``save()`` writes UTF-8 JSON atomically; unknown fields are written back.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from espui.core.checks import validate_project
from espui.core.issues import (
    ProjectFormatError,
    ProjectValidationError,
    issues_from_validation_error,
)
from espui.core.migrate import migrate
from espui.core.models import Project
from espui.i18n import tr

EXTENSIONS = (".espui", ".espui.json")
"""File names accepted by :func:`load`; :func:`save` writes ``.espui``."""


def has_project_extension(path: str | os.PathLike[str]) -> bool:
    return Path(path).name.lower().endswith(EXTENSIONS)


def from_dict(data: Any, *, check: bool = True) -> Project:
    """Migrate + validate a decoded JSON document."""
    migrated = migrate(data)
    try:
        project = Project.model_validate(migrated)
    except ValidationError as error:
        raise ProjectValidationError(issues_from_validation_error(error)) from None
    return validate_project(project) if check else project


def loads(text: str, *, check: bool = True) -> Project:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProjectFormatError(
            tr("Це не JSON-файл проєкту (рядок {lineno}, стовпець {colno})").format(
                lineno=error.lineno, colno=error.colno
            )
        ) from None
    return from_dict(data, check=check)


def load(path: str | os.PathLike[str], *, check: bool = True) -> Project:
    """Open a project file. ``check=False`` skips cross-field checks (drafts)."""
    file = Path(path)
    if not has_project_extension(file):
        kinds = tr(" або ").join("*" + e for e in EXTENSIONS)
        raise ProjectFormatError(
            tr("«{name}»: очікується файл {kinds}").format(name=file.name, kinds=kinds)
        )
    try:
        text = file.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ProjectFormatError(tr("Файл «{file}» не знайдено").format(file=file)) from None
    except UnicodeDecodeError:
        raise ProjectFormatError(
            tr("«{name}» не є текстовим файлом UTF-8").format(name=file.name)
        ) from None
    return loads(text, check=check)


def to_dict(project: Project) -> dict[str, Any]:
    """JSON-ready dict: field aliases (``schema``, ``if``, ``set``), extras included."""
    return project.model_dump(mode="json", by_alias=True)


def dumps(project: Project) -> str:
    return json.dumps(to_dict(project), ensure_ascii=False, indent=2) + "\n"


def save(project: Project, path: str | os.PathLike[str], *, check: bool = True) -> Path:
    """Write ``project`` to ``path`` atomically and return the path written.

    A path without an accepted extension gets ``.espui`` appended.
    """
    if check:
        validate_project(project)
    file = Path(path)
    if not has_project_extension(file):
        file = file.with_name(file.name + ".espui")
    text = dumps(project)
    file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{file.name}.", suffix=".tmp", dir=file.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(tmp, file)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return file


def json_schema() -> dict[str, Any]:
    """JSON Schema of the ``.espui`` structure (``docs/espui.schema.json``).

    Covers what pydantic checks; cross-field rules (:mod:`espui.core.checks`)
    can't be expressed in JSON Schema and are only described in ``description``.
    """
    schema = Project.model_json_schema(by_alias=True, mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ESP UI Builder project (.espui)",
        "description": (  # the same in every interface language
            "The structure of a project file. The app checks the consistency of the fields "
            "(unique names, bindings, conditions, pins for the chip) when it opens a file."
        ),
        **{k: v for k, v in schema.items() if k != "title"},
    }


def schema_text() -> str:
    return json.dumps(json_schema(), ensure_ascii=False, indent=2) + "\n"
