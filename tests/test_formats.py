"""Tests for the helpers shared by jiyuu's readers and writers."""

from pathlib import Path

import pytest

from jiyuu.formats import ink, ink_text, write_text_atomically
from jiyuu.model import MindMap, Node


def test_write_text_atomically_writes_and_leaves_nothing_else(tmp_path: Path) -> None:
    """The file ends up holding exactly the text, and no temporary file is left behind."""
    target = tmp_path / "map.ink"
    write_text_atomically(target, "- Project\r\n")
    assert target.read_bytes() == b"- Project\r\n"
    assert [path.name for path in tmp_path.iterdir()] == ["map.ink"]


def test_a_failed_write_leaves_the_old_file_and_no_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If replacing the file fails, the old file is untouched and the temporary removed."""
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")

    def failing_replace(source: object, destination: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jiyuu.formats.os.replace", failing_replace)
    with pytest.raises(OSError):
        write_text_atomically(target, "new\n")
    assert target.read_text(encoding="utf-8") == "old\n"
    assert [path.name for path in tmp_path.iterdir()] == ["map.ink"]


def test_ink_text_reads_back_as_the_same_tree_and_keeps_other_sections() -> None:
    """The written file is marked as a map, holds the tree as its body, and keeps metadata
    and sections the map came with."""
    mindmap = MindMap(
        root=Node(text="Project", children=[Node(text="Goals")]),
        meta={"title": "Project"},
        other_sections={"outline": "x\n"},
    )
    document = ink.parse(ink_text(mindmap))
    assert document.metadata == {"kind": "mindmap", "title": "Project"}
    assert document.body == "- Project\n  - Goals\n"
    assert document.sections == {"outline": "x\n"}
