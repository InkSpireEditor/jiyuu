"""jiyuu's command-line entry point.

Running `jiyuu` with no arguments, or `poetry run jiyuu` during development, invokes the
Typer application defined here.
"""

import sys
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .formats import describe, ink, mapfile, read_map, write_text_atomically
from .layout import LayoutSettings, resolve_sides
from .measure import PillowMeasurer
from .model import MindMap
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


def _save_beside(mindmap: MindMap, path: Path) -> None:
    """Writes `mindmap` as `<stem>.ink` next to `path`, unless that file already exists.

    A `.ink` file already there is never overwritten: it may hold edits made since it was
    first written, which reopening the original file must not undo. The file that was
    opened is only ever read, and opening a `.ink` file itself writes nothing.

    The sides of the root's children are decided first, the same way the window's layout
    decides them, so that the file records a side for every one of them and the map opens
    the same way from the `.ink` file as from the original.
    """
    target = path.with_suffix(ink.SUFFIX)
    if target == path:
        return
    if target.exists():
        print(f"{target}: already exists, not overwritten", file=sys.stderr)
        return
    resolve_sides(mindmap.root, PillowMeasurer(), LayoutSettings())
    write_text_atomically(target, mapfile.dump(mindmap))
    print(f"{target}: written", file=sys.stderr)


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
    and the window opens regardless. Opening a `.mm` file also writes a `.ink` copy beside
    it, if there is not one already (see `_save_beside`).
    """
    try:
        chosen_theme = load_theme(theme)
    except ThemeError as error:
        print(error, file=sys.stderr)
        raise typer.Exit(code=1) from error

    mindmap, problems = read_map(path)
    for problem in problems:
        print(describe(path, problem), file=sys.stderr)
    if mindmap is None:
        raise typer.Exit(code=1)

    _save_beside(mindmap, path)

    # Imported here rather than at the top: it imports Flet, which every other command
    # does without, and which takes noticeably longer to import than anything else here.
    from .ui.app import run  # pylint: disable=import-outside-toplevel

    run(mindmap, path, chosen_theme)
