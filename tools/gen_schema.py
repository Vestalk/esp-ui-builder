"""Regenerate docs/espui.schema.json from the pydantic models.

python tools/gen_schema.py          # write
python tools/gen_schema.py --check  # exit 1 if the file is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

from espui.core.serializer import schema_text

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "docs" / "espui.schema.json"


def main(argv: list[str]) -> int:
    text = schema_text()
    if "--check" in argv:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != text:
            print(f"{SCHEMA_PATH} is out of date: run python tools/gen_schema.py")
            return 1
        return 0
    SCHEMA_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {SCHEMA_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
