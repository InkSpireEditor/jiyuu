"""Tests for the helpers shared by jiyuu's readers and writers."""

import os
import stat
from pathlib import Path

import pytest

from jiyuu.formats import _can_keep_owner, describe, read_map, write_text_atomically
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


def test_a_new_file_gets_the_permissions_open_would_give_it(tmp_path: Path) -> None:
    target = tmp_path / "map.ink"
    previous = os.umask(0o027)
    try:
        write_text_atomically(target, "- Project\n")
    finally:
        os.umask(previous)
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.parametrize("mode", [0o644, 0o664, 0o600, 0o755])
def test_an_existing_file_keeps_its_permissions(tmp_path: Path, mode: int) -> None:
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")
    target.chmod(mode)
    write_text_atomically(target, "new\n")
    assert stat.S_IMODE(target.stat().st_mode) == mode
    assert target.read_text(encoding="utf-8") == "new\n"


def test_an_existing_file_keeps_its_group(tmp_path: Path) -> None:
    """Given another group the user is in, if there is one."""
    others = [group for group in os.getgroups() if group != os.getegid()]
    if not others:
        pytest.skip("the user is in one group only")
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")
    os.chown(target, -1, others[0])
    write_text_atomically(target, "new\n")
    assert target.stat().st_gid == others[0]


def test_an_existing_file_keeps_its_extended_attributes(tmp_path: Path) -> None:
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")
    try:
        os.setxattr(target, "user.jiyuu-test", b"kept")
    except OSError:
        pytest.skip("the file system does not hold user extended attributes")
    write_text_atomically(target, "new\n")
    assert os.getxattr(target, "user.jiyuu-test") == b"kept"


def test_a_symbolic_link_stays_a_link_and_its_target_is_written(tmp_path: Path) -> None:
    real = tmp_path / "real.ink"
    real.write_text("old\n", encoding="utf-8")
    link = tmp_path / "map.ink"
    link.symlink_to(real)
    write_text_atomically(link, "new\n")
    assert link.is_symlink() and real.read_text(encoding="utf-8") == "new\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["map.ink", "real.ink"]


def test_a_file_with_another_hard_link_is_written_in_place(tmp_path: Path) -> None:
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")
    other = tmp_path / "other.ink"
    os.link(target, other)
    inode = target.stat().st_ino
    write_text_atomically(target, "new\n")
    assert target.stat().st_ino == inode and other.read_text(encoding="utf-8") == "new\n"


def test_a_file_whose_owner_cannot_be_kept_is_written_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """As for a file owned by someone else: a new file could not be given its owner."""
    target = tmp_path / "map.ink"
    target.write_text("old\n", encoding="utf-8")
    inode = target.stat().st_ino
    monkeypatch.setattr("jiyuu.formats._can_keep_owner", lambda before: False)
    write_text_atomically(target, "new\n")
    assert target.stat().st_ino == inode and target.read_text(encoding="utf-8") == "new\n"


def test_a_file_owned_by_someone_else_cannot_have_its_owner_kept() -> None:
    """`_can_keep_owner` for this file's own `stat`, and for one owned by another user."""
    mine = os.stat(__file__)
    assert _can_keep_owner(mine)
    if os.geteuid() != 0:
        theirs = os.stat_result((mine.st_mode, mine.st_ino, mine.st_dev, 1, mine.st_uid + 1, mine.st_gid, 0, 0, 0, 0))
        assert not _can_keep_owner(theirs)
