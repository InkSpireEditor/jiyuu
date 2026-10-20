"""Tests for `jiyuu.taskwarrior`: date conversions, and the real `task` command, run with
`TASKRC` and `TASKDATA` in the test's own folder (see `conftest.py`); those are skipped
where `task` is not installed."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from jiyuu.taskwarrior import (
    Taskwarrior,
    TaskwarriorError,
    from_taskwarrior_date,
    parse_version,
    to_taskwarrior_date,
)

needs_task = pytest.mark.skipif(shutil.which("task") is None, reason="needs taskwarrior's task command")
UUID = "0b6c4e2a-5d1f-4c3e-9a7b-2f8e6d4c1a90"


def test_every_test_has_a_taskwarrior_of_its_own(taskwarrior_of_its_own: Path) -> None:
    """`TASKRC` and `TASKDATA` point into the test's own folder, never at the user's."""
    assert os.environ["TASKRC"] == str(taskwarrior_of_its_own / "taskrc")
    assert os.environ["TASKDATA"] == str(taskwarrior_of_its_own / "data")
    assert not os.environ["TASKDATA"].startswith(str(Path.home() / ".task"))


@pytest.mark.parametrize(
    ("utc", "due"),
    [
        ("20261024T220000Z", "2026-10-25"),  # local midnight, UTC+2
        ("20261101T230000Z", "2026-11-02"),  # local midnight, UTC+1
        ("20261025T120000Z", "2026-10-25T13:00"),
        ("20261025T215959Z", "2026-10-25T22:59"),
    ],
)
def test_dates_are_converted_between_taskwarrior_s_utc_and_local_due_dates(utc: str, due: str) -> None:
    assert from_taskwarrior_date(utc) == due
    if not utc.endswith("59Z"):
        assert to_taskwarrior_date(due) == utc


@pytest.mark.parametrize(("text", "version"), [("3.5.0 (3419d5ba1)\n", (3, 5, 0)), ("2.6.2", (2, 6, 2)), ("x", ())])
def test_parse_version(text: str, version: tuple[int, ...]) -> None:
    assert parse_version(text) == version


def test_a_missing_command_is_not_available_and_raises_when_run() -> None:
    tw = Taskwarrior(command="jiyuu-no-such-command")
    assert not tw.available()
    with pytest.raises(TaskwarriorError, match="cannot be run"):
        tw.export([UUID])


@needs_task
def test_import_then_export_by_uuid() -> None:
    tw = Taskwarrior()
    assert tw.available()
    tw.import_tasks([{"uuid": UUID, "description": "Foo", "status": "pending", "due": "20261024T220000Z"}])
    (task,) = tw.export([UUID, "11111111-1111-4111-8111-111111111111"])
    assert (task["description"], task["status"], task["due"]) == ("Foo", "pending", "20261024T220000Z")
    assert "urgency" in task and "modified" in task
    assert tw.export([]) == []


@needs_task
def test_import_replaces_the_whole_task_and_skips_an_unchanged_one() -> None:
    """The two facts the sync is built on (see the module's docstring)."""
    tw = Taskwarrior()
    tw.import_tasks([{"uuid": UUID, "description": "Foo", "status": "pending", "priority": "H"}])
    (first,) = tw.export([UUID])
    again = {name: value for name, value in first.items() if name not in ("id", "urgency")}
    tw.import_tasks([again])
    (second,) = tw.export([UUID])
    assert second["modified"] == first["modified"]
    tw.import_tasks([{"uuid": UUID, "description": "Foo", "status": "pending"}])
    (third,) = tw.export([UUID])
    assert "priority" not in third


@needs_task
def test_calc_reads_taskwarrior_s_dates_and_refuses_anything_else() -> None:
    tw = Taskwarrior()
    assert tw.calc("2026-10-25") == "2026-10-25"
    assert tw.calc("2026-10-25T14:30") == "2026-10-25T14:30"
    with pytest.raises(ValueError):
        tw.calc("nonsense")


@needs_task
def test_get_reads_a_setting_or_gives_none(taskwarrior_of_its_own: Path) -> None:
    tw = Taskwarrior()
    assert tw.get("jiyuu.urgent") is None
    (taskwarrior_of_its_own / "taskrc").write_text("jiyuu.urgent=12\n", encoding="utf-8")
    assert tw.get("jiyuu.urgent") == "12"


@needs_task
def test_a_failing_command_raises_with_taskwarrior_s_message() -> None:
    with pytest.raises(TaskwarriorError, match="import"):
        Taskwarrior().run(["import"], data="not json")
