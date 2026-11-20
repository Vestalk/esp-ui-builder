"""Display runtime on the MicroPython unix port with fake SPI (real framebuf)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.runtime.contract import DisplayRuntimeContract
from tests.runtime.harness import MicroPythonBackend


class TestDisplayRuntimeMicroPython(DisplayRuntimeContract):
    @pytest.fixture(scope="class")
    @classmethod
    def backend(
        cls, micropython: Path, tmp_path_factory: pytest.TempPathFactory
    ) -> MicroPythonBackend:
        return MicroPythonBackend(micropython, tmp_path_factory.mktemp("mpy-runtime"))

    def test_uses_real_framebuf(self, backend: MicroPythonBackend) -> None:
        assert backend.run("blit", "builtin", 0, 0, 4, 4, 0x00F8)["real_framebuf"] is True
