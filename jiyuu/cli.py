"""jiyuu's command-line entry point.

Running `jiyuu`, or `uv run jiyuu` during development, calls `entry`, which runs the Typer
application defined here. `jiyuu <file>` is short for `jiyuu open <file>`: a first argument
that is an existing file, and not a command's name, is opened (see `with_default_command`).
A file whose name is also a command's, such as `check`, is opened as `jiyuu ./check`. With
no arguments, or a first argument that is neither a command, an option of `jiyuu` itself,
nor an existing file, the help is printed.
"""

import sys
from collections.abc import Collection
from pathlib import Path
from typing import Annotated

import typer
import typer.core
import typer.main

from . import __version__
from . import document
from .formats import describe, ink, mm, read_map, write_text_atomically
from .theme import DEFAULT_THEME, ThemeError, available_themes, load_theme

#: Markdown, so that the lines of one paragraph of a docstring are joined in the help, and
#: `code` is shown as code.
app = typer.Typer(rich_markup_mode="markdown")

#: The description at the top of `jiyuu --help`.
HELP = """A mind map viewer and editor, for FreeMind/Freeplane `.mm` files and jiyuu's own `.ink` files.

`jiyuu <file>` opens a map: it is short for `jiyuu open <file>`."""


@app.callback(help=HELP)
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


@app.command()
def export(
    source: Path,
    target: Path,
    to_mm: Annotated[bool, typer.Option("--mm", help="Write a Freeplane .mm file.")] = False,
    overwrite: Annotated[bool, typer.Option(help="Replace `target` if it already exists.")] = False,
) -> None:
    """Write the map in `source` (a `.ink` or `.mm` file) to `target` in another format.

    `--mm` writes a Freeplane `.mm` file (see `formats.mm.write`). `target` is never
    replaced unless `--overwrite` is given: a `.mm` file may hold Freeplane data that jiyuu
    does not read, and writing over it would lose that data. Problems reading `source` are
    printed; one that leaves no map to write exits non-zero, as does a missing format or an
    existing `target`.
    """
    if not to_mm:
        print("choose a format to export to: --mm", file=sys.stderr)
        raise typer.Exit(code=1)
    mindmap, problems = read_map(source)
    for problem in problems:
        print(describe(source, problem), file=sys.stderr)
    if mindmap is None:
        raise typer.Exit(code=1)
    if target.exists() and not overwrite:
        print(f"{target}: already exists; pass --overwrite to replace it", file=sys.stderr)
        raise typer.Exit(code=1)
    write_text_atomically(target, mm.write(mindmap))
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

    # Absolute, so that the file changes are saved to does not depend on the working
    # directory, which the window changes (see `ui.app.run`).
    doc, problems = document.open_document(path.absolute())
    for problem in problems:
        print(describe(path, problem), file=sys.stderr)
    if doc is None:
        raise typer.Exit(code=1)
    if doc.path is None:
        target = path.with_suffix(ink.SUFFIX)
        print(f"{target}: already exists, not overwritten; changes will be saved under a new name", file=sys.stderr)
    elif doc.path != path.absolute():
        print(f"{doc.path}: written", file=sys.stderr)

    # Imported here rather than at the top: it imports Flet, which every other command
    # does without, and which takes noticeably longer to import than anything else here.
    from .ui.app import run  # pylint: disable=import-outside-toplevel

    run(doc, chosen_theme)
    written = document.close(doc)
    if written is not None:
        print(f"{written}: changes saved", file=sys.stderr)


def command_names() -> set[str]:
    """The names `app`'s commands are invoked by, as the command line reads them."""
    group = typer.main.get_command(app)
    return set(group.commands) if isinstance(group, typer.core.TyperGroup) else set()


def option_names() -> set[str]:
    """The options `jiyuu` itself takes, before any command, such as `--help`."""
    group = typer.main.get_command(app)
    return {name for param in group.params for name in param.opts} | {"--help"}


def with_default_command(args: list[str], commands: Collection[str], options: Collection[str]) -> list[str] | None:
    """`args`, the command-line arguments after the program's name, as `app` should read
    them: unchanged when the first is one of `commands` or `options`, with `open` put first
    when the first is an existing file, and `None` when there are none or the first is
    none of these, for the help to be shown instead."""
    if not args:
        return None
    first = args[0]
    if first in commands or first in options:
        return args
    if not first.startswith("-") and Path(first).is_file():
        return ["open", *args]
    return None


def entry() -> None:
    """The `jiyuu` command: runs `app` on the command line's arguments, with `jiyuu <file>`
    read as `jiyuu open <file>`.

    Without arguments, it prints the help and exits with status 0. With a first argument it
    does not recognise, it says so, prints the help, and exits with status 2, the status
    Typer gives any other wrong command line.
    """
    args = sys.argv[1:]
    rewritten = with_default_command(args, command_names(), option_names())
    if rewritten is not None:
        app(args=rewritten, prog_name="jiyuu")
        return
    if args:
        print(f"jiyuu: {args[0]!r} is not a command, an option, or an existing file\n", file=sys.stderr)
    app(args=["--help"], prog_name="jiyuu", standalone_mode=False)
    sys.exit(2 if args else 0)
