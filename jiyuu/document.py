"""A map open for editing, and the file its changes are saved to.

Changes are saved automatically: `Autosave` saves a `Document` a short while after the
last change to it, so that a burst of changes is written once. There is no explicit save.

Each save first checks that the file on disk is still what this document last read from it
or wrote to it, by comparing a hash of its bytes; `changed_on_disk` makes the same check
without saving, for a caller that watches the file. If something else changed the file in
the meantime — a text editor, a file synchronisation tool, another window — the save does
not happen and the document is marked `conflicted`, so that whoever shows it can ask what to
do: read the file again (`reload`), or write this document's version over it (`keep_mine`).
Autosave writes nothing more until one of the two is chosen.

A Freeplane `.mm` file is only ever read. Opening one saves its map as `<stem>.ink` beside
it, and every change is saved there. If `<stem>.ink` already exists, it may hold changes
made the last time the `.mm` was opened, so this document is given no file at all: a name
must be chosen (`save_as`) before anything is saved.

Every write replaces the file in one step (see `formats.write_text_atomically`), so a write
that fails leaves the file as it was.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .formats import ink, mapfile, read_map, write_text_atomically
from .formats.ink import ERROR, Problem
from .layout import LayoutSettings, resolve_sides, subtree_heights
from .measure import PillowMeasurer
from .model import MindMap

#: How long after the last change a document is saved, in seconds.
SAVE_DELAY = 1.5

#: Something that runs a callback once after a delay in seconds, and returns a function
#: that cancels it if it has not run yet.
Schedule = Callable[[float, Callable[[], None]], Callable[[], object]]


def content_hash(data: bytes) -> bytes:
    """The hash a file's bytes are compared by."""
    return hashlib.blake2b(data).digest()


@dataclass
class Document:
    """A map, the file it was opened from, and the file its changes are saved to."""

    #: The file the map was read from.
    source: Path
    #: The `.ink` file changes are saved to, or `None` until one is chosen.
    path: Path | None
    mindmap: MindMap
    #: The hash of the bytes last read from or written to `path`.
    last_io_hash: bytes
    #: Whether the map has changes not yet saved.
    dirty: bool = False
    #: Whether `path` was found changed by something else; no save happens while it is set.
    conflicted: bool = False


def open_document(path: Path) -> tuple[Document | None, list[Problem]]:
    """The map in `path`, a `.ink` or `.mm` file, opened for editing, and every problem
    found reading it; `None` for the document if no map could be read.

    A `.ink` file is read once, and the bytes read are the ones its hash is taken of, so a
    change made to it after this point is detected by the first save.

    For a `.mm` file, the sides of the root's children are decided first, the way the
    window's layout decides them, so that the `.ink` file written beside it records a side
    for each of them and opens the same way as the `.mm`.
    """
    if path.suffix == ink.SUFFIX:
        try:
            data = path.read_bytes()
            mindmap, problems = mapfile.read(data.decode("utf-8"))
        except (OSError, UnicodeDecodeError) as error:
            return None, [Problem(0, ERROR, f"cannot be read: {error}")]
        if mindmap is None:
            return None, problems
        return Document(path, path, mindmap, content_hash(data)), problems

    mindmap, problems = read_map(path)
    if mindmap is None:
        return None, problems
    target = path.with_suffix(ink.SUFFIX)
    if target.exists():
        return Document(path, None, mindmap, b""), problems
    resolve_sides(mindmap.root, subtree_heights(mindmap.root, PillowMeasurer(), LayoutSettings()))
    text = mapfile.dump(mindmap)
    write_text_atomically(target, text)
    return Document(path, target, mindmap, content_hash(text.encode("utf-8"))), problems


def changed_on_disk(doc: Document) -> bool:
    """Whether `doc`'s file is no longer what `doc` last read from it or wrote to it: its
    bytes differ, or it is gone or cannot be read. `False` for a document with no file."""
    if doc.path is None:
        return False
    try:
        on_disk = doc.path.read_bytes()
    except OSError:
        return True
    return content_hash(on_disk) != doc.last_io_hash


def save(doc: Document) -> None:
    """Writes `doc`'s map to its file, unless the file changed since `doc` last read or
    wrote it: then nothing is written, and `doc` is marked `conflicted`. Does nothing while
    `doc` is already conflicted. `doc` must have a file."""
    if doc.path is None:
        raise ValueError("the document has no file to save to")
    if doc.conflicted:
        return
    if changed_on_disk(doc):
        doc.conflicted = True
        return
    _write(doc, doc.path)


def save_as(doc: Document, path: Path) -> None:
    """Gives `doc` the new file `path` and saves it there. Raises `FileExistsError`, and
    writes nothing, if `path` already exists."""
    if path.exists():
        raise FileExistsError(path)
    _write(doc, path)
    doc.path = path
    doc.conflicted = False


def keep_mine(doc: Document) -> None:
    """Writes `doc`'s map over its file, replacing whatever changed the file, and ends the
    conflict."""
    if doc.path is None:
        raise ValueError("the document has no file to save to")
    _write(doc, doc.path)
    doc.conflicted = False


def reload(doc: Document) -> list[Problem]:
    """Reads `doc`'s file again, replacing its map and dropping every change not saved,
    and ends the conflict; returns every problem found reading it.

    If no map can be read from the file, `doc` is left as it was, still conflicted, and the
    problems say why.
    """
    if doc.path is None:
        raise ValueError("the document has no file to read")
    try:
        data = doc.path.read_bytes()
        mindmap, problems = mapfile.read(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        return [Problem(0, ERROR, f"cannot be read: {error}")]
    if mindmap is None:
        return problems
    doc.mindmap = mindmap
    doc.last_io_hash = content_hash(data)
    doc.dirty = doc.conflicted = False
    return problems


def close(doc: Document) -> Path | None:
    """Saves changes not saved yet, when the map is closed; returns the file written, or
    `None` if there was nothing to save.

    Changes that cannot go to `doc`'s file — it has none, or it changed on disk — are
    written to a new file beside it instead, since nothing can be asked once the window
    is gone: `<stem>.conflict.ink` for a file changed on disk, `<stem>-2.ink` for a map
    given no file, numbered further if that name is taken too.
    """
    if not doc.dirty:
        return None
    if doc.path is not None:
        save(doc)
        if not doc.conflicted:
            return doc.path
        rescue = free_path(doc.path.with_name(f"{doc.path.stem}.conflict{ink.SUFFIX}"))
    else:
        rescue = free_path(doc.source.with_suffix(ink.SUFFIX))
    _write(doc, rescue)
    return rescue


def free_path(path: Path) -> Path:
    """`path` if no file has that name, else the first of `<stem>-2<suffix>`,
    `<stem>-3<suffix>`, ... that is free."""
    candidate, number = path, 1
    while candidate.exists():
        number += 1
        candidate = path.with_name(f"{path.stem}-{number}{path.suffix}")
    return candidate


def _write(doc: Document, path: Path) -> None:
    """Writes `doc`'s map to `path` and records it as what `doc` last wrote."""
    text = mapfile.dump(doc.mindmap)
    write_text_atomically(path, text)
    doc.last_io_hash = content_hash(text.encode("utf-8"))
    doc.dirty = False


class Autosave:
    """Saves one document `SAVE_DELAY` seconds after its last change.

    Each change restarts the wait rather than adding a save, so a burst of changes is
    saved once, after the last of them. `schedule` runs the save; `on_conflict` is called
    when a save finds the file changed on disk.
    """

    def __init__(
        self, doc: Document, schedule: Schedule, on_conflict: Callable[[], None], delay: float = SAVE_DELAY
    ) -> None:
        self.doc = doc
        self.schedule = schedule
        self.on_conflict = on_conflict
        self.delay = delay
        self._cancel: Callable[[], object] | None = None

    def changed(self) -> None:
        """Marks the document changed, and saves it `delay` seconds from now, unless it
        changes again before then. Nothing is scheduled while it has no file or is
        conflicted."""
        self.doc.dirty = True
        self.cancel()
        if self.doc.path is not None and not self.doc.conflicted:
            self._cancel = self.schedule(self.delay, self._save)

    def cancel(self) -> None:
        """Drops the save waiting to happen, if any."""
        if self._cancel is not None:
            self._cancel()
            self._cancel = None

    def _save(self) -> None:
        self._cancel = None
        save(self.doc)
        if self.doc.conflicted:
            self.on_conflict()
