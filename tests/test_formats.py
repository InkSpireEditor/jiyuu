"""Tests for the helpers shared by jiyuu's readers and writers."""

from pathlib import Path

import pytest

from jiyuu.formats import describe, read_map, write_text_atomically
from jiyuu.formats.ink import Problem


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


def test_read_map_reads_an_ink_file(tmp_path: Path) -> None:
    """A `.ink` path goes to the `.ink` reader."""
    path = tmp_path / "map.ink"
    path.write_text("===== ink:body\n- Project\n  - Goals\n", encoding="utf-8")
    mindmap, problems = read_map(path)
    assert mindmap is not None and problems == []
    assert [child.text for child in mindmap.root.children] == ["Goals"]


def test_describe_names_the_path_and_the_line_when_there_is_one() -> None:
    """A problem on a line reads as `path:line: level: message`; one with line `0` has no
    line number."""
    path = Path("map.ink")
    assert describe(path, Problem(5, "warning", "x")) == "map.ink:5: warning: x"
    assert describe(path, Problem(0, "error", "y")) == "map.ink: error: y"
