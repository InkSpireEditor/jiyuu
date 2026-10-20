"""A stand-in for taskwarrior's `task` command, for tests that should not need it installed.

`FakeTaskwarrior` keeps tasks in memory and imports and exports them the way taskwarrior
3.5.0 was measured to: an import replaces the whole task, skips a task imported unchanged,
and otherwise sets `modified` to the time of the import; importing `completed` without an
`end` sets one, importing `pending` removes it; an export gives every status, with an `id`
and an `urgency` added.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence

from jiyuu.taskwarrior import TaskwarriorError


class FakeTaskwarrior:
    """Tasks in memory, by uuid, with a clock that only moves when told to.

    `urgency` gives the urgency an export reports for a uuid (1.0 if absent), `dates` what
    `calc` answers for an expression, `settings` what `get` answers. `failing`, when set,
    is raised by every command; `missing` makes `available` false.
    """

    def __init__(self) -> None:
        self.tasks: dict[str, dict] = {}
        self.now = "20261020T120000Z"
        self.urgency: dict[str, float] = {}
        self.dates: dict[str, str] = {}
        self.settings: dict[str, str] = {}
        self.failing: TaskwarriorError | None = None
        self.missing = False
        #: Each command run, by name: `export`, `import`, `calc`, `get`, `available`.
        self.calls: list[str] = []
        #: The uuids of the tasks each import changed, in order.
        self.imported: list[list[str]] = []

    def _call(self, name: str) -> None:
        self.calls.append(name)
        if self.failing is not None:
            raise self.failing

    def tick(self, seconds: int = 1) -> None:
        """Moves the clock on by `seconds`, within the same day."""
        hours, minutes, secs = int(self.now[9:11]), int(self.now[11:13]), int(self.now[13:15])
        total = hours * 3600 + minutes * 60 + secs + seconds
        self.now = f"{self.now[:9]}{total // 3600:02d}{total // 60 % 60:02d}{total % 60:02d}Z"

    def edit(self, task_uuid: str, **changes: object) -> None:
        """Changes a task as `task modify`, `task done` or `task delete` would: the given
        attributes (`None` removes one), `modified` set to now, and `end` as for an import."""
        task = self.tasks[task_uuid]
        before = copy.deepcopy(task)
        for name, value in changes.items():
            if value is None:
                task.pop(name, None)
            else:
                task[name] = value
        if before.get("status") != task.get("status"):
            before.pop("end", None)
        self._settle(task, before)

    def _settle(self, task: dict, current: dict | None = None) -> None:
        """Fills in what taskwarrior adds to a task it stores: `entry` and `end` as `current`
        had them, or now; `modified` now."""
        current = current or {}
        task.setdefault("entry", current.get("entry", self.now))
        if task.get("status") in ("completed", "deleted"):
            task.setdefault("end", current.get("end", self.now))
        else:
            task.pop("end", None)
        task["modified"] = self.now

    def available(self) -> bool:
        self.calls.append("available")
        return not self.missing

    def export(self, uuids: Sequence[str]) -> list[dict]:
        self._call("export")
        found = [copy.deepcopy(self.tasks[u]) for u in uuids if u in self.tasks]
        for number, task in enumerate(found, start=1):
            task["id"] = number if task.get("status") == "pending" else 0
            task["urgency"] = self.urgency.get(task["uuid"], 1.0)
        return found

    def import_tasks(self, tasks: Sequence[dict]) -> None:
        self._call("import")
        changed = []
        for incoming in tasks:
            assert "id" not in incoming and "urgency" not in incoming
            task = copy.deepcopy(incoming)
            current = self.tasks.get(task["uuid"])
            self._settle(task, current)
            if current is not None and {**task, "modified": current["modified"]} == current:
                continue  # skipped, as taskwarrior skips a task imported unchanged
            self.tasks[task["uuid"]] = task
            changed.append(task["uuid"])
        self.imported.append(changed)

    def calc(self, expression: str) -> str:
        self._call("calc")
        if expression not in self.dates:
            raise ValueError(f"{expression!r} is not a date taskwarrior understands")
        return self.dates[expression]

    def get(self, name: str) -> str | None:
        self._call("get")
        return self.settings.get(name)
