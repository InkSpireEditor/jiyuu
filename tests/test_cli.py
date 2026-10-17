"""Tests for jiyuu's command-line entry point."""

from typer.testing import CliRunner

from jiyuu import __version__
from jiyuu.cli import app

runner = CliRunner()


def test_version_command_prints_the_package_version() -> None:
    """`jiyuu version` prints exactly `jiyuu.__version__`, with no extra output."""
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == __version__
