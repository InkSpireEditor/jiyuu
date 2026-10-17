"""Readers and writers for the file formats jiyuu exchanges maps with."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ..model import MindMap
from . import body, ink, mm

#: File extensions `read_map` has a reader for.
READABLE_SUFFIXES = (".mm", ink.SUFFIX)


def _lines_before_body(text: str, document: ink.Document) -> int:
    """How many lines of the `.ink` file `text` come before its body's first line.

    None, when the whole file is the body (it has no fences, or has text above its first
    one). Otherwise as many as up to the last `ink:body` fence, since a section named twice
    keeps its last occurrence — or none, for a file with no `ink:body` section at all.
    """
    if document.body == text:
        return 0
    fences = [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if ink.section_name(line) == ink.SECTION_BODY
    ]
    return fences[-1] if fences else 0


def read_ink(text: str) -> tuple[MindMap | None, list[str]]:
    """The map in `.ink` file `text`: its tree from the body, its `meta` mapping, and every
    other section kept as text, to be written back with it.

    Problems with the file's sections and with its body are both returned, each as
    `line N: level: message`, with `N` counted in the whole file. Returns `None` for the
    map when the body holds no tree.
    """
    document = ink.parse(text)
    root, body_problems = body.read(document.body)
    offset = _lines_before_body(text, document)
    problems = ink.check(text) + [
        ink.Problem(problem.line + offset, problem.level, problem.message) for problem in body_problems
    ]
    problems.sort(key=lambda problem: (problem.line, problem.level))
    warnings = [f"line {problem.line}: {problem.level}: {problem.message}" for problem in problems]
    if root is None:
        return None, warnings
    mindmap = MindMap(root=root, meta=dict(document.metadata), other_sections=dict(document.sections))
    return mindmap, warnings


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
    if path.suffix == ink.SUFFIX:
        return read_ink(text)
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
