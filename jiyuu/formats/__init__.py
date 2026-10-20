"""Readers and writers for the file formats jiyuu exchanges maps with."""

from __future__ import annotations

import os
import stat
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
    """Writes `text` to `path` so that `path` is never left half-written, keeping what
    belongs to the file rather than to its text.

    The text goes to a temporary file in the same directory first, which is flushed to disk
    and then replaces the file in one step (`os.replace`). If anything fails before that,
    the file is left as it was — or absent, if it did not exist — and the temporary file is
    removed.

    A file that already exists keeps its permission bits, its owner and group, and its
    extended attributes (which hold its ACLs, if it has any): each is given to the temporary
    file before it replaces the old one. A group is set only if the user is in it, and an
    owner only by root, so for a file owned by someone else, or one with a group the user is
    not in, the new file could not carry them. Such a file, and one with more than one hard
    link, which a new file would split from its other names, is written in place instead:
    its owner, group, links and attributes then stay as they are, but a write that fails
    partway can leave it half-written. A symbolic link is followed, and the file it points
    to is written; the link stays a link. A new file gets the permissions `open` would give
    it: 0o666 without the bits of the process's umask.
    """
    target = path.resolve() if path.is_symlink() else path
    try:
        before = target.stat()
    except FileNotFoundError:
        before = None
    if before is not None and (before.st_nlink > 1 or not _can_keep_owner(before)):
        _write_in_place(target, text)
        return
    descriptor, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            if before is None:
                os.fchmod(handle.fileno(), 0o666 & ~_umask())
            else:
                _copy_metadata(target, handle.fileno(), before)
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _can_keep_owner(before: os.stat_result) -> bool:
    """Whether a new file made by this process can be given `before`'s owner and group: it
    has the same owner, or the process is root, and the group is one the process is in."""
    if os.geteuid() == 0:
        return True
    return before.st_uid == os.geteuid() and (before.st_gid == os.getegid() or before.st_gid in os.getgroups())


def _copy_metadata(source: Path, descriptor: int, before: os.stat_result) -> None:
    """Gives the open file `descriptor` the owner, group, permission bits and extended
    attributes of `source`, whose `stat` is `before`. The owner and group are changed only
    if they differ: a new file in a folder with the set-group-id bit already has the
    folder's group. They come first: on
    Linux, changing them clears the set-user-id and set-group-id bits, which the permission
    bits then set again."""
    made = os.fstat(descriptor)
    if (before.st_uid, before.st_gid) != (made.st_uid, made.st_gid):
        os.fchown(descriptor, before.st_uid, before.st_gid)
    os.fchmod(descriptor, stat.S_IMODE(before.st_mode))
    if hasattr(os, "listxattr"):  # extended attributes exist on Linux only
        try:
            names = os.listxattr(source)
        except OSError:
            return
        for name in names:
            try:
                os.setxattr(descriptor, name, os.getxattr(source, name))
            except OSError:
                # Some attributes need privileges to set (`security.*`, `trusted.*`); the
                # file is still written without them.
                pass


def _write_in_place(path: Path, text: str) -> None:
    """Writes `text` over the existing file `path`, keeping the file itself, and flushes
    it to disk."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _umask() -> int:
    """The process's umask. Reading it means setting it, so it is set straight back."""
    mask = os.umask(0o022)
    os.umask(mask)
    return mask
