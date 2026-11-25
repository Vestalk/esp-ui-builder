"""Command-line entry point ``espui``.

Subcommands are registered in :func:`build_parser`; each one is a function
``(args) -> exit code`` stored in ``handler`` so that ``main`` stays closed for
modification when new commands (e.g. ``generate`` in stage 03) are added.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from espui import __version__
from espui.i18n import tr

Handler = Callable[[argparse.Namespace], int]

PROG = "espui"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="ESP32 UI Builder — generates MicroPython UI modules from .espui projects.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    _add_generate(commands)
    gui = commands.add_parser("gui", help="open the desktop application")
    gui.add_argument("project", nargs="?", help="project to open")
    gui.set_defaults(handler=_gui)
    return parser


def _gui(args: argparse.Namespace) -> int:  # pragma: no cover - starts the Qt event loop
    from espui.gui.app import run

    return run(project=args.project)


# ------------------------------------------------------------------ generate
def _add_generate(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    cmd = commands.add_parser(
        "generate",
        help="generate MicroPython files for the board",
        description="Generate MicroPython modules for one page of a .espui project.",
    )
    cmd.add_argument("project", type=Path, help="project file (*.espui or *.espui.json)")
    cmd.add_argument("-o", "--out", type=Path, required=True, help="output folder")
    cmd.add_argument("--page", help="generate only this page (default: all pages)")
    cmd.set_defaults(handler=_generate)


def _generate(args: argparse.Namespace) -> int:
    # Imported lazily: `espui --version` must not pay for pydantic/Jinja.
    from espui.core import serializer
    from espui.core.issues import ProjectError
    from espui.generators.micropython.generator import GenerationError, generate

    try:
        project = serializer.load(args.project)
        result = generate(project, args.page, source=args.project.name)
    except (ProjectError, GenerationError) as error:
        print(tr("Помилка: {error}").format(error=error), file=sys.stderr)
        return 1
    for warning in result.warnings:
        print(tr("Увага: {warning}").format(warning=warning), file=sys.stderr)
    for note in result.notes:
        print(note)
    paths = result.write(args.out)
    titles = ", ".join(f"«{name}»" for name in result.pages)
    label = tr("Сторінка") if len(result.pages) == 1 else tr("Сторінки")
    print(f"{label} {titles} → {args.out}:")
    for path in paths:
        name = path.relative_to(args.out).as_posix()
        if not name.startswith("img/"):  # pictures are summed up in the notes above
            print(f"  {name}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return handler(args)
