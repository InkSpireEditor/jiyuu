"""Tests for jiyuu's command-line entry point."""

from pathlib import Path

from typer.testing import CliRunner

from jiyuu import __version__
from jiyuu.cli import app

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
