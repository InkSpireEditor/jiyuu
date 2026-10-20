"""Shared pytest fixtures for jiyuu's test suite.

Every test runs with taskwarrior's `TASKRC` and `TASKDATA` pointing at an empty
configuration file and a data folder of its own, in the test's temporary folder: a test
that runs `task`, directly or through code that does, never reads or writes the
taskwarrior configuration and tasks of whoever runs the tests.

Every test also runs in the time zone of Paris (`Europe/Paris`), which changes from UTC+2 to
UTC+1 at 03:00 on 2026-10-25: due dates are kept in local time and taskwarrior's in UTC, so
the expected values of a test depend on the time zone, and would otherwise depend on the
machine's.
"""

import os
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def taskwarrior_of_its_own(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A taskwarrior configuration file and data folder for this test alone; returns the
    folder holding both."""
    folder = tmp_path_factory.mktemp("taskwarrior")
    (folder / "taskrc").write_text("", encoding="utf-8")
    (folder / "data").mkdir()
    monkeypatch.setenv("TASKRC", str(folder / "taskrc"))
    monkeypatch.setenv("TASKDATA", str(folder / "data"))
    return folder


@pytest.fixture(autouse=True)
def paris_time() -> Iterator[None]:
    """Local time is Paris time for this test, and the machine's own again after it."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Paris"
    time.tzset()
    yield
    if before is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = before
    time.tzset()
