"""Display runtime on CPython (runs on every OS in CI, also covers st7789py)."""

from __future__ import annotations

import pytest

from tests.runtime.contract import DisplayRuntimeContract
from tests.runtime.harness import CPythonBackend


class TestDisplayRuntimeCPython(DisplayRuntimeContract):
    @pytest.fixture(scope="class")
    @classmethod
    def backend(cls) -> CPythonBackend:
        return CPythonBackend()
