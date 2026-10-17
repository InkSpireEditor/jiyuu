"""Readers and writers for the file formats jiyuu exchanges maps with."""

from __future__ import annotations

from pathlib import Path

from ..model import MindMap
from . import mm

#: File extensions `read_map` has a reader for.
READABLE_SUFFIXES = (".mm",)


def read_map(path: Path) -> tuple[MindMap | None, list[str]]:
    """The map in the file at `path`, read by whichever reader its extension calls for.

    Returns `(None, warnings)` when there is nothing to show: an extension with no reader,
    a file that cannot be read from disk, or one whose reader could not make a tree of it.
    """
    if path.suffix not in READABLE_SUFFIXES:
        return None, [f"no reader for {path.suffix or 'files with no extension'!r} files"]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        return None, [f"cannot be read: {error}"]
    return mm.read(text)
