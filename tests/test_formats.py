"""Tests for the helpers shared by jiyuu's readers and writers."""

from pathlib import Path

import pytest

from jiyuu.formats import ink, ink_text, read_ink, read_map, write_text_atomically
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


INK_FIXTURES = Path(__file__).parent / "data" / "ink"


def test_read_ink_reads_the_tree_and_keeps_meta_and_other_sections() -> None:
    """The worked example reads to its tree; its `meta` is kept, and so is its `nodes`
    section, as text, for writing back."""
    mindmap, warnings = read_ink((INK_FIXTURES / "worked-example.ink").read_text(encoding="utf-8"))

    assert mindmap is not None and warnings == []
    assert mindmap.root.text == "Project"
    assert [child.text for child in mindmap.root.children] == ["Goals", "Risks"]
    assert mindmap.meta == {"kind": "mindmap", "title": "Project"}
    assert list(mindmap.other_sections) == ["nodes"]


def test_read_ink_numbers_body_problems_by_line_in_the_whole_file() -> None:
    """A body problem on the body's second line, in a file whose body starts on line 4,
    is reported on line 5."""
    _, warnings = read_ink("===== ink:meta\nkind: mindmap\n===== ink:body\n- Project\n  Goals\n")
    assert warnings == ["line 5: warning: this line has no '-', '*' or '+' marker"]


def test_read_ink_of_a_file_with_no_fences_numbers_from_the_top() -> None:
    """A file with no fences is all body, so its lines are the body's lines."""
    _, warnings = read_ink("- Project\n  Goals\n")
    assert warnings == ["line 2: warning: this line has no '-', '*' or '+' marker"]


def test_read_ink_counts_from_the_last_body_fence_when_there_are_two() -> None:
    """A body opened twice keeps the second one, so line numbers count from there; the
    repeated section is reported too."""
    _, warnings = read_ink("===== ink:body\n- One\n===== ink:body\n- Project\n  Goals\n")
    assert warnings == [
        'line 3: error: the section "body" is opened more than once',
        "line 5: warning: this line has no '-', '*' or '+' marker",
    ]


def test_read_ink_with_no_body_has_no_map() -> None:
    """A file with sections but no body section has no tree to show."""
    mindmap, warnings = read_ink("===== ink:meta\nkind: mindmap\n")
    assert mindmap is None
    assert "empty" in warnings[0]


def test_read_map_reads_an_ink_file(tmp_path: Path) -> None:
    """A `.ink` path goes to the `.ink` reader."""
    path = tmp_path / "map.ink"
    path.write_text("- Project\n  - Goals\n", encoding="utf-8")
    mindmap, _ = read_map(path)
    assert mindmap is not None
    assert [child.text for child in mindmap.root.children] == ["Goals"]
