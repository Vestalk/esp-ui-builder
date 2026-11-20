"""Fixtures for running code on the MicroPython unix port.

The binary is taken from ``$ESPUI_MICROPYTHON`` or ``micropython`` on PATH.
Without it, every test in this folder is skipped (CI builds it on Linux).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

RunMpy = Callable[[str], subprocess.CompletedProcess[str]]


def _find_micropython() -> Path | None:
    env = os.environ.get("ESPUI_MICROPYTHON")
    if env:
        return Path(env)
    found = shutil.which("micropython")
    return Path(found) if found else None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.fspath).parents:
            item.add_marker(pytest.mark.mpy)


@pytest.fixture(scope="session")
def micropython() -> Path:
    path = _find_micropython()
    if path is None or not path.exists():
        pytest.skip("MicroPython unix port not found (set ESPUI_MICROPYTHON)")
    return path


@pytest.fixture
def run_mpy(micropython: Path, tmp_path: Path) -> RunMpy:
    def run(source: str) -> subprocess.CompletedProcess[str]:
        script = tmp_path / "main.py"
        script.write_text(source, encoding="utf-8")
        return subprocess.run(
            [str(micropython), "-X", "heapsize=16M", str(script)],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_path,
            check=False,
        )

    return run
