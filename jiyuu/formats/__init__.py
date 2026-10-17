"""Readers and writers for the file formats jiyuu exchanges maps with."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..model import MindMap
from . import body, ink, mm

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


def ink_text(mindmap: MindMap) -> str:
    """`mindmap` as the text of a `.ink` file: its `meta` section, marked `kind: mindmap`,
    and its tree as the body. Folding and sides are not written yet."""
    metadata = {"kind": "mindmap", **mindmap.meta}
    return ink.render(metadata, body.write(mindmap.root), dict(mindmap.other_sections))
