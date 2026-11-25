"""Shared test setup: the tests check the Ukrainian texts (the source language)."""

from __future__ import annotations

import os

os.environ["ESPUI_LANG"] = "uk"  # before espui.i18n is imported anywhere
