"""Tests for `jiyuu.document`: opening a map for editing, saving it shortly after changes,
noticing a file changed on disk, and saving what is left when the map is closed."""

import os
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from jiyuu import document
from jiyuu.document import (
    Autosave,
    Document,
    changed_on_disk,
    close,
    free_path,
    keep_mine,
    open_document,
    reload,
    save,
    save_as,
)

MM_FIXTURES = Path(__file__).parent / "data" / "mm"
INK = "- Project\n  - Goals\n"


class _Clock:
    """A clock that only moves when told to, running each callback scheduled on it once
    its time has come."""

    def __init__(self) -> None:
        self.now = 0.0
        #: Each callback scheduled and not cancelled, with the time it is due.
        self.pending: list[tuple[float, Callable[[], None]]] = []

    def schedule(self, delay: float, callback: Callable[[], None]) -> Callable[[], object]:
        """Runs `callback` once `delay` more seconds have passed; returns its cancel."""
        entry = (self.now + delay, callback)
        self.pending.append(entry)
        return lambda: self.pending.remove(entry)

    def advance(self, seconds: float) -> None:
        """Moves the clock on by `seconds`, running every callback that falls due."""
        self.now += seconds
        due = [entry for entry in self.pending if entry[0] <= self.now]
        for entry in due:
            self.pending.remove(entry)
            entry[1]()


def _ink(tmp_path: Path, text: str = INK) -> Document:
    """A `.ink` file holding `text`, opened."""
    path = tmp_path / "map.ink"
    path.write_text(text, encoding="utf-8")
    doc, _ = open_document(path)
    assert doc is not None
    return doc


def _count_writes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every path written from here on, in order."""
    written: list[Path] = []
    original = document.write_text_atomically

    def counting(path: Path, text: str) -> None:
        written.append(path)
        original(path, text)

    monkeypatch.setattr(document, "write_text_atomically", counting)
    return written


def test_opening_an_ink_file_reads_it_and_writes_nothing(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    assert doc.source == doc.path == tmp_path / "map.ink"
    assert doc.mindmap.root.text == "Project"
    assert not doc.dirty and not doc.conflicted
    assert [p.name for p in tmp_path.iterdir()] == ["map.ink"]


def test_five_changes_within_the_delay_are_saved_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each change restarts the wait: five changes 0.3 s apart are saved once, 1.5 s after
    the last of them."""
    doc = _ink(tmp_path)
    clock = _Clock()
    autosave = Autosave(doc, clock.schedule, lambda: None)
    written = _count_writes(monkeypatch)

    for _ in range(5):
        doc.mindmap.root.text += "!"
        autosave.changed()
        clock.advance(0.3)
    assert written == []
    clock.advance(1.0)
    assert written == []
    clock.advance(0.5)

    assert written == [doc.path]
    assert not doc.dirty
    assert "- Project!!!!!\n" in (tmp_path / "map.ink").read_text(encoding="utf-8")


def test_opening_a_mm_file_saves_changes_beside_it_and_never_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "worked-example.mm"
    shutil.copyfile(MM_FIXTURES / "worked-example.mm", source)
    original = source.read_bytes()
    doc, _ = open_document(source)
    assert doc is not None
    assert doc.path == tmp_path / "worked-example.ink" and doc.path.exists()

    clock = _Clock()
    autosave = Autosave(doc, clock.schedule, lambda: None)
    written = _count_writes(monkeypatch)
    doc.mindmap.root.text = "Plans"
    autosave.changed()
    clock.advance(2.0)

    assert written == [tmp_path / "worked-example.ink"]
    assert source.read_bytes() == original


def test_a_mm_file_whose_ink_exists_gets_no_file_and_nothing_scheduled(tmp_path: Path) -> None:
    source = tmp_path / "worked-example.mm"
    shutil.copyfile(MM_FIXTURES / "worked-example.mm", source)
    (tmp_path / "worked-example.ink").write_text(INK, encoding="utf-8")
    doc, _ = open_document(source)
    assert doc is not None and doc.path is None

    clock = _Clock()
    Autosave(doc, clock.schedule, lambda: None).changed()
    assert doc.dirty and clock.pending == []
    assert (tmp_path / "worked-example.ink").read_text(encoding="utf-8") == INK


def test_a_file_changed_on_disk_between_two_saves_is_not_overwritten(tmp_path: Path) -> None:
    """The second save finds the file changed since the first, writes nothing, and marks
    the document conflicted; the autosave reports it."""
    doc = _ink(tmp_path)
    clock = _Clock()
    conflicts: list[bool] = []
    autosave = Autosave(doc, clock.schedule, lambda: conflicts.append(True))
    autosave.changed()
    clock.advance(2.0)

    path = tmp_path / "map.ink"
    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    doc.mindmap.root.text = "Plans"
    autosave.changed()
    clock.advance(2.0)

    assert doc.conflicted and conflicts == [True]
    assert path.read_text(encoding="utf-8") == "- Edited elsewhere\n"
    autosave.changed()
    assert clock.pending == []  # nothing more is scheduled while conflicted


def test_a_deleted_file_is_a_conflict_too(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    (tmp_path / "map.ink").unlink()
    save(doc)
    assert doc.conflicted and not (tmp_path / "map.ink").exists()


def test_a_write_that_fails_leaves_the_file_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Writing the temporary file raises partway; the map's file keeps its bytes, and no
    temporary file is left behind."""
    doc = _ink(tmp_path)
    path = tmp_path / "map.ink"
    original = path.read_bytes()
    real_fdopen = os.fdopen

    class _Failing:
        def __init__(self, handle) -> None:
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            self.handle.close()

        def write(self, text: str) -> None:
            self.handle.write(text[:5])
            raise OSError("disk full")

    monkeypatch.setattr(os, "fdopen", lambda *args, **kwargs: _Failing(real_fdopen(*args, **kwargs)))
    doc.mindmap.root.text = "Plans"
    with pytest.raises(OSError):
        save(doc)

    assert path.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["map.ink"]


def test_keep_mine_writes_over_the_changed_file_and_saving_resumes(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    path = tmp_path / "map.ink"
    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    doc.mindmap.root.text = "Plans"
    save(doc)
    assert doc.conflicted

    keep_mine(doc)
    assert not doc.conflicted and not doc.dirty
    assert "- Plans\n" in path.read_text(encoding="utf-8")

    doc.mindmap.root.text = "Plans again"
    save(doc)
    assert not doc.conflicted
    assert "- Plans again\n" in path.read_text(encoding="utf-8")


def test_reload_reads_the_changed_file_and_drops_unsaved_changes(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    (tmp_path / "map.ink").write_text("- Edited elsewhere\n", encoding="utf-8")
    doc.mindmap.root.text = "Plans"
    doc.dirty = True
    save(doc)

    reload(doc)
    assert doc.mindmap.root.text == "Edited elsewhere"
    assert not doc.conflicted and not doc.dirty
    doc.mindmap.root.text = "Plans"
    save(doc)
    assert not doc.conflicted


def test_reload_of_an_unreadable_file_keeps_the_conflict(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    (tmp_path / "map.ink").write_text("===== ink:body\n", encoding="utf-8")
    save(doc)
    problems = reload(doc)
    assert problems and doc.conflicted
    assert doc.mindmap.root.text == "Project"


def test_save_as_writes_a_new_file_and_refuses_an_existing_one(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    original = (tmp_path / "map.ink").read_bytes()
    with pytest.raises(FileExistsError):
        save_as(doc, tmp_path / "map.ink")

    doc.mindmap.root.text = "Plans"
    save_as(doc, tmp_path / "other.ink")
    assert doc.path == tmp_path / "other.ink"
    assert "- Plans\n" in (tmp_path / "other.ink").read_text(encoding="utf-8")
    assert (tmp_path / "map.ink").read_bytes() == original


def test_close_saves_only_unsaved_changes(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    assert close(doc) is None
    doc.mindmap.root.text = "Plans"
    doc.dirty = True
    assert close(doc) == tmp_path / "map.ink"
    assert "- Plans\n" in (tmp_path / "map.ink").read_text(encoding="utf-8")


def test_close_writes_changes_beside_a_file_changed_on_disk(tmp_path: Path) -> None:
    doc = _ink(tmp_path)
    (tmp_path / "map.ink").write_text("- Edited elsewhere\n", encoding="utf-8")
    doc.mindmap.root.text = "Plans"
    doc.dirty = True

    assert close(doc) == tmp_path / "map.conflict.ink"
    assert (tmp_path / "map.ink").read_text(encoding="utf-8") == "- Edited elsewhere\n"
    assert "- Plans\n" in (tmp_path / "map.conflict.ink").read_text(encoding="utf-8")


def test_close_writes_changes_of_a_map_given_no_file_to_a_new_name(tmp_path: Path) -> None:
    source = tmp_path / "worked-example.mm"
    shutil.copyfile(MM_FIXTURES / "worked-example.mm", source)
    (tmp_path / "worked-example.ink").write_text(INK, encoding="utf-8")
    doc, _ = open_document(source)
    assert doc is not None
    doc.dirty = True

    assert close(doc) == tmp_path / "worked-example-2.ink"
    assert (tmp_path / "worked-example.ink").read_text(encoding="utf-8") == INK


def test_free_path_numbers_a_taken_name(tmp_path: Path) -> None:
    path = tmp_path / "map.ink"
    assert free_path(path) == path
    path.write_text(INK, encoding="utf-8")
    (tmp_path / "map-2.ink").write_text(INK, encoding="utf-8")
    assert free_path(path) == tmp_path / "map-3.ink"


def test_changed_on_disk(tmp_path: Path) -> None:
    """Unchanged after opening and after a save; changed once something else writes the
    file, or removes it."""
    doc = _ink(tmp_path)
    path = tmp_path / "map.ink"
    assert not changed_on_disk(doc)
    doc.mindmap.root.text = "Plans"
    save(doc)
    assert not changed_on_disk(doc)
    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    assert changed_on_disk(doc)
    path.unlink()
    assert changed_on_disk(doc)
