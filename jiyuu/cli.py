"""jiyuu's command-line entry point.

Running `jiyuu` with no arguments, or `poetry run jiyuu` during development, invokes the
Typer application defined here.
"""

import sys
from pathlib import Path

import typer

from . import __version__
from .formats import mm

app = typer.Typer()


@app.callback()
def main() -> None:
    """jiyuu's top-level command group.

    Typer collapses an app with exactly one registered command into that command itself, so
    it would be invoked with no name at all. Defining this callback, even though it does
    nothing on its own, keeps every command — `version` today, more as jiyuu grows — invoked
    by name instead.
    """


@app.command()
def version() -> None:
    """Print jiyuu's installed version."""
    print(__version__)


@app.command()
def check(path: Path) -> None:
    """Print every problem reading `path` found, one per line.

    Exits with a non-zero status only if `path` could not be read into a map at all;
    printing warnings for a file that otherwise read fine still exits zero.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".mm":
        mindmap, warnings = mm.read(text)
    else:
        print(f"jiyuu check does not know the file type {path.suffix!r}", file=sys.stderr)
        raise typer.Exit(code=1)

    for warning in warnings:
        print(warning)
    if mindmap is None:
        raise typer.Exit(code=1)
