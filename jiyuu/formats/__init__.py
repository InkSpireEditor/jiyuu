"""Readers and writers for the file formats jiyuu exchanges maps with."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..model import MindMap
from . import ink, mapfile, mm
from .ink import ERROR, WARNING, Problem

#: File extensions `read_map` has a reader for.
READABLE_SUFFIXES = (".mm", ink.SUFFIX)


def read_map(path: Path) -> tuple[MindMap | None, list[Problem]]:
    """The map in the file at `path`, read by whichever reader its extension calls for,
    and every problem found reading it.

    Returns `None` for the map when there is nothing to show: an extension with no reader,
    a file that cannot be read from disk, or one whose reader could not make a tree of it.
    A problem with no line of its own — anything about a `.mm` file, whose reader does not
    track lines, or about the file as a whole — has line `0`.
    """
    if path.suffix not in READABLE_SUFFIXES:
        return None, [Problem(0, ERROR, f"no reader for {path.suffix or 'files with no extension'!r} files")]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return None, [Problem(0, ERROR, f"cannot be read: {error}")]
    if path.suffix == ink.SUFFIX:
        return mapfile.read(text)
    mindmap, warnings = mm.read(text)
    problems = [Problem(0, WARNING, warning) for warning in warnings]
    if mindmap is None:
        # The `.mm` reader gives up on the last thing it reports.
        problems[-1] = Problem(0, ERROR, warnings[-1])
    return mindmap, problems


def describe(path: Path, problem: Problem) -> str:
    """`problem` as one line naming `path`: `path:line: level: message`, or
    `path: level: message` for a problem with no line of its own."""
    where = f"{path}:{problem.line}" if problem.line else f"{path}"
    return f"{where}: {problem.level}: {problem.message}"


def write_text_atomically(path: Path, text: str) -> None:
    """Writes `text` to `path` so that `path` is never left half-written.

    The text goes to a temporary file in the same directory first, which then replaces
    `path` in one step (`os.replace`). If anything fails before that, `path` is left as it
    was — or absent, if it did not exist — and the temporary file is removed.
    """
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
