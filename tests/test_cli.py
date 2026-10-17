"""Tests for jiyuu's command-line entry point."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from jiyuu import __version__
from jiyuu.cli import app
from jiyuu.model import MindMap
from jiyuu.theme import DEFAULT_THEME, Theme, load_theme

runner = CliRunner()

MM_FIXTURES = Path(__file__).parent / "data" / "mm"


def test_version_command_prints_the_package_version() -> None:
    """`jiyuu version` prints exactly `jiyuu.__version__`, with no extra output."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__


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


def test_open_hands_the_map_and_theme_to_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """`jiyuu open` reads the file and the theme, then passes both to the window."""
    opened: dict = {}

    def fake_run(mindmap: MindMap, path: Path, theme: Theme) -> None:
        opened.update(root=mindmap.root.text, path=path, theme=theme.name)

    monkeypatch.setattr("jiyuu.ui.app.run", fake_run)
    path = MM_FIXTURES / "worked-example.mm"
    result = runner.invoke(app, ["open", str(path), "--theme", "solarized-dark"])

    assert result.exit_code == 0
    assert opened == {"root": "Project", "path": path, "theme": "Solarized Dark"}


def test_open_uses_the_default_theme_when_none_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no `--theme`, the window gets the default theme."""
    themes: list[str] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda mindmap, path, theme: themes.append(theme.name))
    result = runner.invoke(app, ["open", str(MM_FIXTURES / "worked-example.mm")])

    assert result.exit_code == 0
    assert themes == [load_theme(DEFAULT_THEME).name]


def test_open_stops_before_any_window_for_an_unknown_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    """A theme that cannot be loaded exits non-zero, and the window is never opened."""
    calls: list[object] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: calls.append(args))
    result = runner.invoke(app, ["open", str(MM_FIXTURES / "worked-example.mm"), "--theme", "nope"])

    assert result.exit_code != 0
    assert calls == []


def test_open_stops_before_any_window_for_an_unreadable_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """A file that cannot be read into a map exits non-zero, and the window is never opened."""
    calls: list[object] = []
    monkeypatch.setattr("jiyuu.ui.app.run", lambda *args: calls.append(args))
    result = runner.invoke(app, ["open", str(MM_FIXTURES / "malformed.mm")])

    assert result.exit_code != 0
    assert calls == []
