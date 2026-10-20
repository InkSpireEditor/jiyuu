"""Tests for jiyuu's command-line entry point."""

import json
import shutil
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from jiyuu import __version__
from jiyuu.cli import app, command_names, entry, option_names, with_default_command
from jiyuu.formats import ink, mm
from jiyuu.document import Document
from jiyuu.taskwarrior import Taskwarrior, TaskwarriorError
from jiyuu.theme import DEFAULT_THEME, Theme, load_theme

from .stand_ins import FakeTaskwarrior

runner = CliRunner()

MM_FIXTURES = Path(__file__).parent / "data" / "mm"


def test_version_command_prints_the_package_version() -> None:
    """`jiyuu version` prints exactly `jiyuu.__version__`, with no extra output, and that is
    the version written in `pyproject.toml`."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    pyproject = tomllib.loads((Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8"))
    assert result.stdout.strip() == __version__ == pyproject["project"]["version"]


def test_check_on_a_clean_mm_file_prints_nothing_and_exits_zero() -> None:
    """A file that reads with no warnings at all produces no output, and succeeds."""
    result = runner.invoke(app, ["check", str(MM_FIXTURES / "worked-example.mm")])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_check_on_a_file_with_warnings_prints_them_but_still_exits_zero() -> None:
    """Warnings alone, for a file that still read into a map, do not fail the command."""
    result = runner.invoke(app, ["check", str(MM_FIXTURES / "freeplane-extras.mm")])
    assert result.exit_code == 0
    assert result.stdout.strip() != ""


def test_check_on_an_unreadable_file_exits_non_zero() -> None:
    """A file that cannot be read into a map at all is the one case that fails."""
    result = runner.invoke(app, ["check", str(MM_FIXTURES / "malformed.mm")])
    assert result.exit_code != 0
    assert "could not be parsed" in result.stdout


def test_check_on_an_unknown_file_type_exits_non_zero(tmp_path: Path) -> None:
    """A file extension `check` has no reader for is reported, not guessed at."""
    unknown = tmp_path / "map.txt"
    unknown.write_text("hello", encoding="utf-8")
    result = runner.invoke(app, ["check", str(unknown)])
    assert result.exit_code != 0


def _fixture_copy(tmp_path: Path, name: str) -> Path:
    """A copy of a `.mm` fixture in `tmp_path`, so that the `.ink` `open` writes beside it
    lands there rather than in the repository."""
    copy = tmp_path / name
    shutil.copyfile(MM_FIXTURES / name, copy)
    return copy


def test_open_hands_the_map_and_theme_to_the_window(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`jiyuu open` reads the file and the theme, then passes both to the window."""
    opened: dict = {}

    def fake_run(doc: Document, theme: Theme) -> None:
        opened.update(root=doc.mindmap.root.text, source=doc.source, path=doc.path, theme=theme.name)

    monkeypatch.setattr("jiyuu.ui.app.run", fake_run)
    path = _fixture_copy(tmp_path, "worked-example.mm")
    result = runner.invoke(app, ["open", str(path), "--theme", "solarized-dark"])

    assert result.exit_code == 0
    assert opened == {
        "root": "Project",
        "source": path,
        "path": path.with_suffix(".ink"),
        "theme": "Solarized Dark",
    }


def test_open_uses_the_default_theme_when_none_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """With no `--theme`, the window gets the default theme."""
    themes: list[str] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda doc, theme: themes.append(theme.name))
    result = runner.invoke(app, ["open", str(_fixture_copy(tmp_path, "worked-example.mm"))])

    assert result.exit_code == 0
    assert themes == [load_theme(DEFAULT_THEME).name]


def test_open_stops_before_any_window_for_an_unknown_theme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A theme that cannot be loaded exits non-zero; no window opens and nothing is
    written."""
    calls: list[object] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: calls.append(args))
    path = _fixture_copy(tmp_path, "worked-example.mm")
    result = runner.invoke(app, ["open", str(path), "--theme", "nope"])

    assert result.exit_code != 0
    assert calls == []
    assert not path.with_suffix(".ink").exists()


def test_open_stops_before_any_window_for_an_unreadable_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A file that cannot be read into a map exits non-zero; no window opens and nothing
    is written."""
    calls: list[object] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: calls.append(args))
    path = _fixture_copy(tmp_path, "malformed.mm")
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code != 0
    assert calls == []
    assert not path.with_suffix(".ink").exists()


def test_open_writes_the_map_as_ink_beside_it(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Opening `worked-example.mm` writes `worked-example.ink` next to it, holding the same
    tree as an indented list, and leaves the `.mm` exactly as it was."""
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: None)
    path = _fixture_copy(tmp_path, "worked-example.mm")
    original = path.read_bytes()
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code == 0
    assert path.read_bytes() == original
    assert path.with_suffix(".ink").read_text(encoding="utf-8") == (
        "===== ink:meta\n"
        "kind: mindmap\n"
        "===== ink:body\n"
        "- Project\n"
        "  - Goals\n"
        "    - I/O\n"
        "  - Risks\n"
        "    - Flet performance\n"
        "===== ink:nodes\n"
        '"7be48fc73f0ebe9c": {side: "right"}\n'
        '"32a21dfedf2cf99c": {side: "left", folded: "true"}\n'
    )


def test_open_records_a_side_for_every_first_level_node(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `.mm` whose first-level nodes have no `POSITION` still gets a side written for
    each of them in the `.ink`, decided the way the window's layout decides it."""
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: None)
    path = tmp_path / "map.mm"
    path.write_text(
        '<map><node TEXT="Project"><node TEXT="Goals"/><node TEXT="Risks"/></node></map>',
        encoding="utf-8",
    )
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code == 0
    written = ink.parse(path.with_suffix(".ink").read_text(encoding="utf-8"))
    assert written.sections == {
        "nodes": '"7be48fc73f0ebe9c": {side: "right"}\n"32a21dfedf2cf99c": {side: "left"}\n'
    }


def test_open_never_overwrites_an_existing_ink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `.ink` already beside the `.mm` is left untouched, and the window still opens,
    with no file to save to until one is named."""
    docs: list[Document] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda doc, theme: docs.append(doc))
    path = _fixture_copy(tmp_path, "worked-example.mm")
    existing = path.with_suffix(".ink")
    existing.write_text("- edited by hand\n", encoding="utf-8")
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code == 0
    assert existing.read_text(encoding="utf-8") == "- edited by hand\n"
    assert [doc.path for doc in docs] == [None]


def test_open_saves_changes_left_unsaved_when_the_window_closes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A change made just before the window closes, not yet saved, is saved after it
    closes, and the file is named on the terminal."""

    def edit(doc: Document, _theme: Theme) -> None:
        doc.mindmap.root.text = "Plans"
        doc.dirty = True

    monkeypatch.setattr("jiyuu.ui.app.run", edit)
    path = tmp_path / "map.ink"
    path.write_text("- Project\n  - Goals\n", encoding="utf-8")
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code == 0
    assert "- Plans\n  - Goals\n" in path.read_text(encoding="utf-8")
    assert f"{path}: changes saved" in result.output


def test_opening_an_ink_file_writes_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A `.ink` file opens in the window, and is left exactly as it was."""
    calls: list[object] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: calls.append(args))
    path = tmp_path / "map.ink"
    path.write_text("- Project\n  - Goals\n", encoding="utf-8")
    result = runner.invoke(app, ["open", str(path)])

    assert result.exit_code == 0
    assert len(calls) == 1
    assert path.read_text(encoding="utf-8") == "- Project\n  - Goals\n"
    assert [p.name for p in tmp_path.iterdir()] == ["map.ink"]


def test_check_reports_a_task_whose_entry_matches_no_task(tmp_path: Path) -> None:
    """The task fixture is clean; with its synced task renamed by hand, `check` warns that
    the task's entry matches no task, and still succeeds."""
    fixture = Path(__file__).parent / "data" / "ink" / "tasks.ink"
    assert runner.invoke(app, ["check", str(fixture)]).stdout == ""
    renamed = tmp_path / "tasks.ink"
    renamed.write_text(fixture.read_text(encoding="utf-8").replace("[ ] Foo  due", "[ ] Fooo  due"), encoding="utf-8")
    result = runner.invoke(app, ["check", str(renamed)])
    assert result.exit_code == 0
    assert "the task entry for 'Foo' matches no task in the body" in result.stdout


def test_check_on_a_clean_ink_file_prints_nothing() -> None:
    """A `.ink` file with nothing wrong produces no output, and succeeds."""
    result = runner.invoke(app, ["check", str(Path(__file__).parent / "data" / "ink" / "worked-example.ink")])
    assert result.exit_code == 0
    assert result.stdout == ""


def test_check_on_a_hand_edited_ink_file_prints_its_problems_by_line(tmp_path: Path) -> None:
    """A warning in a `.ink` file is printed with the path and its line number in the whole
    file, and the command still succeeds."""
    path = tmp_path / "map.ink"
    path.write_text("===== ink:meta\nkind: mindmap\n===== ink:body\n- Project\n  Goals\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(path)])
    assert result.exit_code == 0
    assert result.stdout == f"{path}:5: warning: this line has no '-', '*' or '+' marker\n"


def test_check_on_an_ink_file_with_an_error_exits_non_zero(tmp_path: Path) -> None:
    """An error fails the command, even though a map could still be read."""
    path = tmp_path / "map.ink"
    path.write_text("===== ink:meta\nkind: mindmap\n===== ink:body\n- Project\n- Extra\n", encoding="utf-8")
    result = runner.invoke(app, ["check", str(path)])
    assert result.exit_code != 0
    assert result.stdout.startswith(f"{path}:5: error: ")


def test_check_prints_mm_problems_with_no_line_number() -> None:
    """The `.mm` reader does not track lines, so its problems name only the file."""
    path = MM_FIXTURES / "freeplane-extras.mm"
    result = runner.invoke(app, ["check", str(path)])
    assert result.stdout.startswith(f"{path}: warning: ")


def test_export_writes_a_mm_file_that_reads_back_as_the_same_tree(tmp_path: Path) -> None:
    source = tmp_path / "map.ink"
    source.write_text("- Project\n  - Goals\n  - Risks\n", encoding="utf-8")
    target = tmp_path / "map.mm"
    result = runner.invoke(app, ["export", "--mm", str(source), str(target)])

    assert result.exit_code == 0
    exported, _ = mm.read(target.read_text(encoding="utf-8"))
    assert exported is not None
    assert [child.text for child in exported.root.children] == ["Goals", "Risks"]


def test_export_refuses_an_existing_target_unless_told_to_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "map.ink"
    source.write_text("- Project\n", encoding="utf-8")
    target = tmp_path / "map.mm"
    target.write_text("<map/>", encoding="utf-8")

    result = runner.invoke(app, ["export", "--mm", str(source), str(target)])
    assert result.exit_code != 0
    assert target.read_text(encoding="utf-8") == "<map/>"

    result = runner.invoke(app, ["export", "--mm", "--overwrite", str(source), str(target)])
    assert result.exit_code == 0
    assert 'TEXT="Project"' in target.read_text(encoding="utf-8")


def test_export_needs_a_format_and_a_readable_source(tmp_path: Path) -> None:
    source = tmp_path / "map.ink"
    source.write_text("- Project\n", encoding="utf-8")
    assert runner.invoke(app, ["export", str(source), str(tmp_path / "out.mm")]).exit_code != 0
    assert runner.invoke(app, ["export", "--mm", str(tmp_path / "missing.ink"), str(tmp_path / "out.mm")]).exit_code != 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["map.ink"]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["map.ink"], ["open", "map.ink"]),
        (["map.ink", "--theme", "nord"], ["open", "map.ink", "--theme", "nord"]),
        (["./check"], ["open", "./check"]),
        (["check", "map.ink"], ["check", "map.ink"]),
        (["open", "map.ink"], ["open", "map.ink"]),
        (["--help"], ["--help"]),
        ([], None),
        (["chek"], None),  # neither a command nor a file
        (["missing.ink"], None),
        (["--foo"], None),
    ],
)
def test_with_default_command(
    args: list[str], expected: list[str] | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """In a folder holding `map.ink` and a file named `check`: an existing file is opened,
    a command or `jiyuu`'s own option is passed on, and anything else gives `None`."""
    (tmp_path / "map.ink").write_text("- Project\n", encoding="utf-8")
    (tmp_path / "check").write_text("- Project\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert with_default_command(args, command_names(), option_names()) == expected


def test_command_and_option_names() -> None:
    assert command_names() == {"version", "check", "export", "open", "task-sync"}
    assert "--help" in option_names()


def _entry(argv: list[str], calls: list[tuple[list[str], str]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs `entry` with `argv` after the program's name, with `app` adding each call to
    `calls` instead of running."""
    commands, options = command_names(), option_names()
    monkeypatch.setattr("sys.argv", ["jiyuu", *argv])
    monkeypatch.setattr("jiyuu.cli.command_names", lambda: commands)
    monkeypatch.setattr("jiyuu.cli.option_names", lambda: options)
    monkeypatch.setattr("jiyuu.cli.app", lambda args, prog_name, **_: calls.append((args, prog_name)))
    entry()


def test_entry_opens_an_existing_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "map.ink").write_text("- Project\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    calls: list[tuple[list[str], str]] = []
    _entry(["map.ink"], calls, monkeypatch)
    assert calls == [(["open", "map.ink"], "jiyuu")]


@pytest.mark.parametrize(("argv", "status"), [([], 0), (["chek"], 2), (["--foo"], 2)])
def test_entry_shows_the_help_for_no_or_an_unknown_first_argument(
    argv: list[str], status: int, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The help is asked for; an unknown argument is named on standard error first; the
    exit status is 0 without arguments and 2 otherwise."""
    calls: list[tuple[list[str], str]] = []
    with pytest.raises(SystemExit) as stopped:
        _entry(argv, calls, monkeypatch)
    assert stopped.value.code == status
    assert calls == [(["--help"], "jiyuu")]
    error = capsys.readouterr().err
    assert (argv[0] in error) if argv else error == ""


def test_the_help_shown_is_the_full_one(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """With the real `app`, an unknown command prints every command and the
    `jiyuu <file>` shorthand."""
    monkeypatch.setattr("sys.argv", ["jiyuu", "chek"])
    with pytest.raises(SystemExit):
        entry()
    output = capsys.readouterr()
    assert "'chek' is not a command" in output.err
    for name in ("open", "check", "export", "version", "jiyuu open <file>"):
        assert name in output.out


def test_open_with_a_relative_path_saves_to_an_absolute_one(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The window changes the working directory, so the document's file must not depend
    on it."""
    docs: list[Document] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda doc, theme: docs.append(doc))
    (tmp_path / "map.ink").write_text("- Project\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["open", "map.ink"])

    assert result.exit_code == 0
    assert [doc.path for doc in docs] == [tmp_path / "map.ink"]
    assert docs[0].path is not None and docs[0].path.is_absolute()


TASKS_MAP = "===== ink:body\n- Project\n  - Goals\n    - [ ] Foo  due:2026-10-25 priority:H\n    - [x] Bar\n"


def _fake_taskwarrior(monkeypatch: pytest.MonkeyPatch) -> FakeTaskwarrior:
    tw = FakeTaskwarrior()
    monkeypatch.setattr("jiyuu.cli.Taskwarrior", lambda: tw)
    return tw


def test_task_sync_creates_the_tasks_and_writes_their_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tw = _fake_taskwarrior(monkeypatch)
    path = tmp_path / "tasks.ink"
    path.write_text(TASKS_MAP, encoding="utf-8")
    result = runner.invoke(app, ["task-sync", str(path)])
    assert result.exit_code == 0
    assert "tasks: 2 created" in result.stdout and "written" in result.stdout
    assert {task["project"] for task in tw.tasks.values()} == {"tasks"}
    text = path.read_text(encoding="utf-8")
    assert text.count('kind: "task"') == 2

    again = runner.invoke(app, ["task-sync", str(path)])
    assert again.exit_code == 0 and "written" not in again.stdout
    assert path.read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [("map.mm", "<map/>", 2), ("map.ink", "===== ink:meta\nkind: mindmap\n", 2)],
    ids=["not a .ink file", "no map in it"],
)
def test_task_sync_refuses_what_it_cannot_sync(tmp_path: Path, name: str, content: str, code: int) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    assert runner.invoke(app, ["task-sync", str(path)]).exit_code == code


def test_task_sync_fails_without_taskwarrior_and_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tw = _fake_taskwarrior(monkeypatch)
    tw.missing = True
    path = tmp_path / "tasks.ink"
    path.write_text(TASKS_MAP, encoding="utf-8")
    result = runner.invoke(app, ["task-sync", str(path)])
    assert result.exit_code == 1 and "cannot be run" in result.stderr
    assert path.read_text(encoding="utf-8") == TASKS_MAP


def test_task_sync_reports_a_failing_taskwarrior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tw = _fake_taskwarrior(monkeypatch)
    tw.failing = TaskwarriorError("task import: disk full")
    path = tmp_path / "tasks.ink"
    path.write_text(TASKS_MAP, encoding="utf-8")
    result = runner.invoke(app, ["task-sync", str(path)])
    assert result.exit_code == 1 and "disk full" in result.stderr
    assert path.read_text(encoding="utf-8") == TASKS_MAP


@pytest.mark.skipif(shutil.which("task") is None, reason="needs taskwarrior's task command")
def test_task_sync_with_the_real_taskwarrior(tmp_path: Path) -> None:
    """Against `task` itself, in the test's own taskwarrior: a first sync creates the two
    tasks, one done in taskwarrior is ticked in the file by the next."""
    path = tmp_path / "tasks.ink"
    path.write_text(TASKS_MAP, encoding="utf-8")
    assert runner.invoke(app, ["task-sync", str(path)]).exit_code == 0
    tw = Taskwarrior()
    pending = [task for task in json.loads(tw.run(["project:tasks", "export"])) if task["status"] == "pending"]
    assert [task["description"] for task in pending] == ["Foo"]
    tw.run([pending[0]["uuid"], "done"])
    assert runner.invoke(app, ["task-sync", str(path)]).exit_code == 0
    assert "    - [x] Foo  due:2026-10-25 priority:H\n" in path.read_text(encoding="utf-8")
