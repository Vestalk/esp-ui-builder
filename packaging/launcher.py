"""Entry point of the PyInstaller build: the app without arguments, the CLI with them.

espui                      -> opens the program
espui generate x.espui -o out/  -> command line, as ``espui`` from pip
"""

import sys

from espui.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["gui"]))
