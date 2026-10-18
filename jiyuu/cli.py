"""jiyuu's command-line entry point.

Running `jiyuu` with no arguments, or `poetry run jiyuu` during development, invokes the
Typer application defined here.
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from . import document
from .formats import describe, ink, read_map
from .theme import DEFAULT_THEME, ThemeError, available_themes, load_theme

app = typer.Typer()


@app.callback()
def main() -> None:
    """jiyuu's top-level command group.

    Typer collapses an app with exactly one registered command into that command itself, so
    it would be invoked with no name at all. Defining this callback, even though it does
    nothing on its own, keeps every command invoked by name instead.
    """


@app.command()
def version() -> None:
    """Print jiyuu's installed version."""
    print(__version__)


@app.command()
def check(path: Path) -> None:
    """Print every problem reading `path` found, one per line, as `path:line: level:
    message`.

    Exits with a non-zero status if `path` could not be read into a map at all, or if any
    problem is an error; warnings alone, for a file that otherwise read fine, exit zero.
    """
    mindmap, problems = read_map(path)
    for problem in problems:
        print(describe(path, problem))
    if mindmap is None or any(problem.level == ink.ERROR for problem in problems):
        raise typer.Exit(code=1)


@app.command("open")
def open_map(
    path: Path,
    theme: Annotated[
        str,
        typer.Option(help=f"A bundled theme ({', '.join(available_themes())}) or a .yaml path."),
    ] = DEFAULT_THEME,
) -> None:
    """Open the map in `path` (a `.mm` or `.ink` file) in a window.

    The theme and the file are both read before any window opens, so that a theme or a
    file that cannot be used is reported on the terminal and exits non-zero, rather than
    opening an empty window. Problems with a file that did read are printed the same way,
    and the window opens regardless.

    Changes made in the window are saved as they are made (see `jiyuu.document`). Opening a
    `.mm` file writes a `.ink` copy beside it, which changes are saved to, and never writes
    the `.mm` itself. If that `.ink` already exists, it is left untouched, and the window
    asks for another name before saving any change. Changes still unsaved when the window
    closes are saved then, and the file they went to is printed.
    """
    try:
        chosen_theme = load_theme(theme)
    except ThemeError as error:
        print(error, file=sys.stderr)
        raise typer.Exit(code=1) from error

    doc, problems = document.open_document(path)
    for problem in problems:
        print(describe(path, problem), file=sys.stderr)
    if doc is None:
        raise typer.Exit(code=1)
    if doc.path is None:
        target = path.with_suffix(ink.SUFFIX)
        print(f"{target}: already exists, not overwritten; changes will be saved under a new name", file=sys.stderr)
    elif doc.path != path:
        print(f"{doc.path}: written", file=sys.stderr)

    # Imported here rather than at the top: it imports Flet, which every other command
    # does without, and which takes noticeably longer to import than anything else here.
    from .ui.app import run  # pylint: disable=import-outside-toplevel

    run(doc, chosen_theme)
    written = document.close(doc)
    if written is not None:
        print(f"{written}: changes saved", file=sys.stderr)
