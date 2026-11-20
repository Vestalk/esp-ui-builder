from __future__ import annotations

import subprocess
import sys

import pytest

from espui import __version__
from espui.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_no_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: espui" in capsys.readouterr().out


def test_python_m_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "espui", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert __version__ in result.stdout
