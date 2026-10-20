"""Talking to taskwarrior (https://taskwarrior.org) through its `task` command.

Everything goes through `task`'s command line, as a subprocess; taskwarrior's database is
never read or written directly. `task` reads its configuration from `~/.taskrc` and its data
from the folder that configuration names, or from the files the `TASKRC` and `TASKDATA`
environment variables name instead.

Each command is run with three configuration overrides: `rc.confirmation=off`, so that no
command stops to ask a question; `rc.verbose=nothing`, so that only the command's own output
is printed; and `rc.json.array=on`, so that `task export` prints one JSON array. Its input is
closed when nothing is sent to it, so that a `task` missing its configuration file exits with
an error rather than waiting for an answer.

Two facts about `task import` (taskwarrior 3.5.0) shape how it is used:

- It replaces the whole task: an attribute missing from the imported JSON is removed from the
  task. A task is therefore changed by exporting it, changing attributes in the exported
  JSON, and importing that.
- A task imported unchanged is skipped, and keeps its `modified` time; a task imported with
  any difference gets `modified` set to the time of the import.

Taskwarrior writes dates in UTC, `20261024T220000Z`. A task's due date is kept in a map in
local time, as a date, `2026-10-25`, when it falls at local midnight, and otherwise as a date
and a time to the minute, `2026-10-25T14:00` (see `jiyuu.formats.body`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

#: The configuration overrides every `task` command is run with.
OVERRIDES = ("rc.confirmation=off", "rc.verbose=nothing", "rc.json.array=on")
#: The format of a date in taskwarrior's JSON.
DATE_FORMAT = "%Y%m%dT%H%M%SZ"
#: The oldest taskwarrior whose `task import` and `task export` work as this module expects.
MINIMUM_VERSION = (2, 6)


class TaskwarriorError(Exception):
    """A `task` command that could not be run, or that failed; the message says why."""


def from_taskwarrior_date(value: str) -> str:
    """Taskwarrior's UTC date `value` as a due date in local time: a date alone at local
    midnight, otherwise a date and a time to the minute."""
    moment = datetime.strptime(value, DATE_FORMAT).replace(tzinfo=UTC).astimezone()
    return local_due(moment.replace(tzinfo=None))


def to_taskwarrior_date(due: str) -> str:
    """Due date `due`, in local time (see `from_taskwarrior_date`), as taskwarrior's UTC date."""
    return datetime.fromisoformat(due).astimezone().astimezone(UTC).strftime(DATE_FORMAT)


def local_due(moment: datetime) -> str:
    """Local time `moment`, with no time zone, as a due date: a date alone at midnight,
    otherwise a date and a time to the minute."""
    if (moment.hour, moment.minute, moment.second) == (0, 0, 0):
        return moment.date().isoformat()
    return moment.strftime("%Y-%m-%dT%H:%M")


def parse_version(text: str) -> tuple[int, ...]:
    """The numbers at the start of a version such as `3.5.0`, as a tuple: `(3, 5, 0)`;
    empty if `text` does not start with a number."""
    match = re.match(r"\d+(\.\d+)*", text.strip())
    return tuple(int(part) for part in match[0].split(".")) if match else ()


class Taskwarrior:
    """The `task` command, run with `OVERRIDES`.

    `command` is the program to run. `environment`, if given, is the whole environment
    `task` runs with, instead of this process's own.
    """

    def __init__(self, command: str = "task", environment: Mapping[str, str] | None = None) -> None:
        self.command = command
        self.environment = dict(environment) if environment is not None else None

    def run(self, arguments: Sequence[str], data: str | None = None) -> str:
        """The output of `task` run with `arguments`, and `data` as its input if given.
        Raises `TaskwarriorError` if `task` cannot be run or exits with a non-zero status."""
        try:
            completed = subprocess.run(
                [self.command, *OVERRIDES, *arguments],
                input=data,
                stdin=subprocess.DEVNULL if data is None else None,
                capture_output=True,
                text=True,
                env=self.environment if self.environment is not None else os.environ.copy(),
                check=False,
            )
        except OSError as error:
            raise TaskwarriorError(f"taskwarrior's {self.command!r} command cannot be run: {error}") from error
        if completed.returncode != 0:
            reason = completed.stderr.strip() or completed.stdout.strip() or f"exit status {completed.returncode}"
            raise TaskwarriorError(f"task {' '.join(arguments[:1])}: {reason}")
        return completed.stdout

    def version(self) -> tuple[int, ...]:
        """Taskwarrior's version, as numbers: `(3, 5, 0)`. Asked with `task _version`,
        which prints it followed by a build id, `3.5.0 (3419d5ba1)`: `task --version` exits
        with status 1 when configuration overrides come before it."""
        return parse_version(self.run(["_version"]))

    def available(self) -> bool:
        """Whether `task` can be run, and is taskwarrior `MINIMUM_VERSION` or later."""
        try:
            return self.version() >= MINIMUM_VERSION
        except TaskwarriorError:
            return False

    def export(self, uuids: Sequence[str]) -> list[dict]:
        """The tasks with `uuids`, whatever their status, as taskwarrior's JSON. A uuid
        taskwarrior has no task for is left out without an error."""
        if not uuids:
            return []
        loaded = json.loads(self.run([*uuids, "export"]) or "[]")
        if not isinstance(loaded, list):
            raise TaskwarriorError("task export: did not print a JSON array")
        return [task for task in loaded if isinstance(task, dict)]

    def import_tasks(self, tasks: Sequence[dict]) -> None:
        """Creates or replaces each of `tasks`, by its uuid, with one `task import`."""
        if tasks:
            self.run(["import"], data=json.dumps(list(tasks)))

    def calc(self, expression: str) -> str:
        """The due date `expression` means to taskwarrior (`tomorrow`, `friday`, `eow`,
        `2026-10-25`), in local time (see `local_due`). Raises `ValueError` if taskwarrior
        does not read it as a date: `task calc` prints such an expression back unchanged."""
        output = self.run(["calc", expression]).strip()
        try:
            moment = datetime.fromisoformat(output)
        except ValueError as error:
            raise ValueError(f"{expression!r} is not a date taskwarrior understands") from error
        if moment.tzinfo is not None:
            moment = moment.astimezone().replace(tzinfo=None)
        return local_due(moment)

    def get(self, name: str) -> str | None:
        """The value of configuration setting `name` (`task _get rc.<name>`), or `None` if
        it is not set."""
        value = self.run(["_get", f"rc.{name}"]).strip()
        return value or None
