"""Runs ``runtime_scenarios`` on CPython or on the MicroPython unix port.

Both backends expose the same ``Backend.run(scenario, *args)`` interface
(strategy), so one contract test-suite checks the runtime on both.
"""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from functools import cached_property
from pathlib import Path
from typing import Any

from espui.generators.micropython.drivers import RUNTIME_DIR

SCENARIOS_DIR = Path(__file__).parent
RUNTIME_MODULES = ("ui_display", "ui_st7789", "ui_tft", "st7789py")


class ScenarioUnavailableError(RuntimeError):
    """The backend cannot run this scenario (e.g. no viper on this unix port)."""


class Backend(ABC):
    name: str

    @abstractmethod
    def run(self, scenario: str, *args: Any) -> Any: ...

    @property
    @abstractmethod
    def has_native_emitter(self) -> bool:
        """Whether ``@micropython.viper`` code (st7789py) can be compiled."""


class CPythonBackend(Backend):
    name = "cpython"

    def __init__(self) -> None:
        for path in (str(RUNTIME_DIR), str(SCENARIOS_DIR)):
            if path not in sys.path:
                sys.path.insert(0, path)
        for module in (*RUNTIME_MODULES, "runtime_scenarios"):
            sys.modules.pop(module, None)
        self._scenarios = importlib.import_module("runtime_scenarios")

    @property
    def has_native_emitter(self) -> bool:
        return True  # st7789py falls back to plain functions on CPython

    def run(self, scenario: str, *args: Any) -> Any:
        result = getattr(self._scenarios, scenario)(*args)
        # Round-trip through JSON so both backends return identical shapes.
        return json.loads(json.dumps(result))


class MicroPythonBackend(Backend):
    name = "micropython"

    def __init__(self, binary: Path, workdir: Path) -> None:
        self._binary = binary
        self._workdir = workdir
        for name in (*RUNTIME_MODULES, "runtime_scenarios"):
            src_dir = SCENARIOS_DIR if name == "runtime_scenarios" else RUNTIME_DIR
            shutil.copy(src_dir / f"{name}.py", workdir / f"{name}.py")

    def _exec(self, source: str) -> subprocess.CompletedProcess[str]:
        script = self._workdir / "main.py"
        script.write_text(source, encoding="utf-8")
        return subprocess.run(
            [str(self._binary), str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=self._workdir,
            check=False,
        )

    @cached_property
    def has_native_emitter(self) -> bool:
        probe = self._exec(
            "import micropython\n"
            "@micropython.viper\n"
            "def f(x: int) -> int:\n"
            "    return x\n"
            "print(f(7))\n"
        )
        return probe.returncode == 0 and probe.stdout.strip() == "7"

    def run(self, scenario: str, *args: Any) -> Any:
        call_args = ", ".join(_mpy_literal(a) for a in args)
        result = self._exec(
            "import json, runtime_scenarios\n"
            f"print(json.dumps(runtime_scenarios.{scenario}({call_args})))\n"
        )
        if result.returncode != 0:
            raise AssertionError(f"MicroPython failed:\n{result.stdout}\n{result.stderr}")
        return json.loads(result.stdout.strip().splitlines()[-1])


def _mpy_literal(value: Any) -> str:
    if isinstance(value, bool | int | str) or value is None:
        return repr(value)
    raise TypeError(f"unsupported scenario argument {value!r}")
