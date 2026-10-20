"""Syncing a map's tasks with taskwarrior (https://taskwarrior.org).

Each task node of a map is kept as one taskwarrior task. A node's link to its task
(`model.TaskLink`) records the task's uuid, taskwarrior's `modified` time of it at the last
sync, and the node's text and task as they were then. A sync compares both sides with that
record:

- A task node with no link is created in taskwarrior.
- A linked node changed only in the map since the last sync sends its text, done or not,
  due date and priority to taskwarrior; changed only in taskwarrior (its `modified` is
  not earlier than the link's), it takes them from there. Changed on both sides, the later change
  wins: the map's time is given by the caller, taskwarrior's is the task's `modified`.
- Ticked done in the map, the task is completed in taskwarrior, and the other way round;
  unticked, it is pending again.
- A task deleted in taskwarrior deletes its node, and the node's branch, from the map; the
  tasks of other task nodes in that branch are deleted in taskwarrior too.
- A node that is no longer a task, and a link whose node is gone from the map
  (`MindMap.orphan_tasks`), have their task deleted in taskwarrior, and the link dropped.

Every task also gets the map's file name without its suffix as its `project`, and the map's
absolute path in an attribute `jiyuumap`, which taskwarrior keeps although it does not know
it: `task project:example list`, or `task jiyuumap:/path/to/example.ink list`, lists one
map's tasks. A task created in taskwarrior is not added to any map.

A sync makes three `task` commands: one `task export` of every linked task, one `task
import` of every task with jiyuu's attributes changed in taskwarrior's own JSON (so that
tags, annotations and anything else set in taskwarrior are kept; taskwarrior skips a task
imported unchanged), and one more `task export` to read back each task's `modified` time
and `urgency`.

The work is split in three, so that a window can run the part that waits on taskwarrior
away from the thread its map is changed on: `snapshot` records the map's task nodes,
`run_sync` talks to taskwarrior from that record alone, and `apply` changes the map. `sync`
does all three in turn.

A task created by a sync gets a uuid derived from the map's path and the node's id
(`uuid.uuid5`), rather than a random one. If the map could not be saved after a sync, the
node is still unlinked at the next sync, which then updates the same task instead of
creating a second one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .model import PRIORITIES, MindMap, Node, Task, TaskLink, node_id, parent_of, path_of, walk
from .taskwarrior import (
    DATE_FORMAT,
    Taskwarrior,
    TaskwarriorError,
    from_taskwarrior_date,
    to_taskwarrior_date,
)

#: The taskwarrior attribute holding the absolute path of a task's map.
MAP_ATTRIBUTE = "jiyuumap"
#: The taskwarrior setting holding the urgency from which a task is drawn as urgent.
URGENT_SETTING = "jiyuu.urgent"
#: The urgency from which a task is drawn as urgent, when `URGENT_SETTING` is not set. With
#: taskwarrior's default urgency coefficients, a task due today with no priority has an
#: urgency of about 9.2, and one due tomorrow about 8.8.
DEFAULT_URGENT = 9.0
#: The attributes of taskwarrior's exported JSON that `task import` does not take back.
_EXPORT_ONLY = ("id", "urgency")
#: The statuses of a task that is not done and not deleted.
_OPEN_STATUSES = ("pending", "waiting", "recurring")


@dataclass(frozen=True)
class TaskState:
    """One node that is a task, or has a task link, as it was when a snapshot was taken.

    `node` is only used to find the node again; everything compared is held here. `key` is
    the node's id, which a new task's uuid is derived from. `ancestors` are the nodes above
    it, root first.
    """

    node: Node
    key: str
    text: str
    task: Task | None
    link: TaskLink | None
    ancestors: tuple[Node, ...]


@dataclass(frozen=True)
class Snapshot:
    """A map's task nodes and orphaned task links, as they were at one moment."""

    tasks: tuple[TaskState, ...]
    orphans: tuple[TaskLink, ...]


@dataclass(frozen=True)
class Update:
    """The text, task and link a node gets from a sync."""

    node: Node
    text: str
    task: Task | None
    link: TaskLink | None


@dataclass
class SyncResult:
    """What a sync did in taskwarrior, and what it changes in the map."""

    #: Each node whose text, task or link the sync changes.
    updates: list[Update] = field(default_factory=list)
    #: Each node deleted from the map, with its branch, because its task was deleted in
    #: taskwarrior.
    removed: list[Node] = field(default_factory=list)
    #: The uuids of the orphaned links dropped.
    dropped_orphans: list[str] = field(default_factory=list)
    #: The urgency taskwarrior gives each task node that is not done.
    urgency: dict[Node, float] = field(default_factory=dict)
    #: How many tasks were created, updated from the map, updated from taskwarrior into the
    #: map, and deleted in taskwarrior.
    created: int = 0
    sent: int = 0
    copied: int = 0
    deleted: int = 0
    #: Whether `apply` changed the map.
    changed: bool = False

    def summary(self) -> str:
        """One line saying what the sync did."""
        parts = [
            f"{self.created} created",
            f"{self.sent} updated from the map",
            f"{self.copied} updated from taskwarrior",
            f"{self.deleted} deleted in taskwarrior",
            f"{len(self.removed)} nodes deleted from the map",
        ]
        return "tasks: " + ", ".join(parts)


def snapshot(mindmap: MindMap) -> Snapshot:
    """`mindmap`'s task nodes, and the nodes that are not tasks but still have a task
    link, in body order, with its orphaned task links."""
    states: list[TaskState] = []

    def visit(node: Node, above: tuple[Node, ...]) -> None:
        for child in node.children:
            if child.task is not None or child.task_link is not None:
                key = node_id(path_of(child, mindmap.root))
                states.append(TaskState(child, key, child.text, child.task, child.task_link, (*above, node)))
            visit(child, (*above, node))

    visit(mindmap.root, ())
    return Snapshot(tuple(states), tuple(mindmap.orphan_tasks))


def new_uuid(map_path: Path, key: str) -> str:
    """The uuid a task created for the node with id `key`, in the map at `map_path`, gets."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{map_path.as_uri()}#{key}"))


def _importable(stored: dict) -> dict:
    """Taskwarrior's exported JSON for one task, without what `task import` does not take."""
    return {name: value for name, value in stored.items() if name not in _EXPORT_ONLY}


def _deleted(stored: dict) -> dict:
    """The JSON that deletes the task `stored` describes."""
    return {**_importable(stored), "status": "deleted"}


def task_json(stored: dict, task_uuid: str, text: str, task: Task, map_path: Path) -> dict:
    """The JSON to import for a task with `text` and `task`, from map `map_path`: `stored`,
    taskwarrior's own JSON for it (empty for a new task), with jiyuu's attributes set.

    A due date that already means `task.due` is kept as taskwarrior wrote it, so that a due
    time with seconds, set in taskwarrior, is not changed by being sent back to the minute.
    """
    data = _importable(stored)
    data.update(uuid=task_uuid, description=text, project=map_path.stem)
    data[MAP_ATTRIBUTE] = str(map_path)
    if task.done:
        if data.get("status") != "completed":
            data["status"] = "completed"
    elif data.get("status") not in _OPEN_STATUSES:
        data["status"] = "pending"
        data.pop("end", None)
    if task.due is None:
        data.pop("due", None)
    elif "due" not in data or from_taskwarrior_date(data["due"]) != task.due:
        data["due"] = to_taskwarrior_date(task.due)
    if task.priority is None:
        data.pop("priority", None)
    else:
        data["priority"] = task.priority
    return data


def map_values(stored: dict) -> tuple[str, Task]:
    """The node text and task that taskwarrior's JSON `stored` describes."""
    priority = stored.get("priority")
    due = stored.get("due")
    task = Task(
        done=stored.get("status") == "completed",
        due=from_taskwarrior_date(due) if due else None,
        priority=priority if priority in PRIORITIES else None,
    )
    return " ".join(str(stored.get("description", "")).split()), task


def _moment(value: str) -> datetime:
    """Taskwarrior's UTC date `value` as an aware `datetime`."""
    return datetime.strptime(value, DATE_FORMAT).replace(tzinfo=UTC)


class _Run:
    """One sync's decisions, made from taskwarrior's tasks as exported at its start
    (`exported`, by uuid): the JSON to import, the tasks kept in the map, and the result."""

    def __init__(self, exported: dict[str, dict], map_path: Path, map_time: datetime) -> None:
        self.exported = exported
        self.map_path = map_path
        self.map_time = map_time
        self.result = SyncResult()
        self.imports: list[dict] = []
        #: Each task that stays in the map, by uuid: its state, and its text and task once
        #: synced.
        self.kept: dict[str, tuple[TaskState, str, Task]] = {}

    def add(self, state: TaskState, task_uuid: str, removed: set[Node]) -> None:
        """Decides what to do with `state`, whose task has `task_uuid`, given the nodes
        `removed` from the map because their task was deleted in taskwarrior."""
        if state.node in removed:
            self.result.removed.append(state.node)
            return
        if state.task is None or removed.intersection(state.ancestors):
            # No longer a task, or in a branch deleted from the map: its task goes.
            self.delete(task_uuid)
            if state.task is None:
                self.result.updates.append(Update(state.node, state.text, None, None))
            return
        stored = self.exported.get(task_uuid)
        text, task = self._values(state, state.task, stored)
        self.imports.append(task_json(stored or {}, task_uuid, text, task, self.map_path))
        self.kept[task_uuid] = (state, text, task)

    def _values(self, state: TaskState, current: Task, stored: dict | None) -> tuple[str, Task]:
        """The text and task `state`'s node has once synced, `current` being its task now
        and `stored` taskwarrior's JSON for it, if taskwarrior has it."""
        if state.link is None or stored is None:
            # A new task; or one created by a sync whose map was not saved afterwards, which
            # keeps whatever was added to it in taskwarrior since; or one gone from
            # taskwarrior, created again.
            self.result.created += stored is None
            return state.text, current
        map_changed = (state.text, current) != (state.link.text, state.link.task)
        modified = stored.get("modified", "")
        # `modified` has a resolution of one second, so a change made in taskwarrior in the
        # same second as the last sync has the same time as the link. Taking the task's
        # values in that case only changes something if it did change.
        tw_changed = modified >= state.link.synced
        if tw_changed and (not map_changed or _moment(modified) > self.map_time):
            text, task = map_values(stored)
            self.result.copied += (text, task) != (state.text, current)
            return text, task
        self.result.sent += map_changed
        return state.text, current

    def delete(self, task_uuid: str) -> None:
        """Deletes the task with `task_uuid` in taskwarrior, if it has one not deleted yet."""
        stored = self.exported.get(task_uuid)
        if stored is not None and stored.get("status") != "deleted":
            self.imports.append(_deleted(stored))
            self.result.deleted += 1

    def read_back(self, after: dict[str, dict]) -> None:
        """Records each kept task's new link, and its urgency, from taskwarrior's tasks as
        exported after the import (`after`, by uuid)."""
        for task_uuid, (state, text, task) in self.kept.items():
            stored = after.get(task_uuid)
            if stored is None:
                raise TaskwarriorError(f"task import: task {task_uuid} was not imported")
            link = TaskLink(task_uuid, stored.get("modified", ""), text, task)
            if (text, task, link) != (state.text, state.task, state.link):
                self.result.updates.append(Update(state.node, text, task, link))
            if stored.get("status") in _OPEN_STATUSES:
                self.result.urgency[state.node] = float(stored.get("urgency", 0.0))


def run_sync(snap: Snapshot, taskwarrior: Taskwarrior, map_path: Path, map_time: datetime) -> SyncResult:
    """Syncs the tasks in `snap`, of the map whose file is `map_path` and which last changed
    at `map_time` (an aware `datetime`), with taskwarrior; returns what to change in the map.
    Changes nothing in the map itself. Raises `TaskwarriorError` if a `task` command fails.
    """
    uuids = {
        state.node: state.link.uuid if state.link is not None else new_uuid(map_path, state.key)
        for state in snap.tasks
    }
    exported = {
        task["uuid"]: task for task in taskwarrior.export([*uuids.values(), *(link.uuid for link in snap.orphans)])
    }
    run = _Run(exported, map_path, map_time)
    removed = {
        state.node
        for state in snap.tasks
        if state.task is not None
        and state.link is not None
        and exported.get(state.link.uuid, {}).get("status") == "deleted"
    }
    for state in snap.tasks:
        run.add(state, uuids[state.node], removed)
    for link in snap.orphans:
        run.delete(link.uuid)
        run.result.dropped_orphans.append(link.uuid)
    taskwarrior.import_tasks(run.imports)
    run.read_back({task["uuid"]: task for task in taskwarrior.export(list(run.kept))})
    return run.result


def apply(mindmap: MindMap, result: SyncResult) -> bool:
    """Makes `result`'s changes to `mindmap`, the map it was synced from; returns whether
    anything changed, and records it in `result.changed`. A node no longer in the tree is
    left alone."""
    changed = False
    in_tree = set(walk(mindmap.root))
    for update in result.updates:
        node = update.node
        if node not in in_tree or (node.text, node.task, node.task_link) == (update.text, update.task, update.link):
            continue
        node.text, node.task, node.task_link = update.text, update.task, update.link
        changed = True
    for node in result.removed:
        try:
            parent = parent_of(node, mindmap.root)
        except ValueError:  # not in the tree, or in a branch already removed
            continue
        if parent is not None:
            parent.children.remove(node)
            changed = True
    kept = [link for link in mindmap.orphan_tasks if link.uuid not in result.dropped_orphans]
    if len(kept) != len(mindmap.orphan_tasks):
        mindmap.orphan_tasks[:] = kept
        changed = True
    result.changed = changed
    return changed


def sync(mindmap: MindMap, taskwarrior: Taskwarrior, map_path: Path, map_time: datetime) -> SyncResult:
    """Syncs `mindmap`'s tasks with taskwarrior and changes the map to match; see
    `run_sync` and `apply`."""
    result = run_sync(snapshot(mindmap), taskwarrior, map_path, map_time)
    apply(mindmap, result)
    return result


def urgent_threshold(taskwarrior: Taskwarrior) -> float:
    """The urgency from which a task is drawn as urgent: taskwarrior's `URGENT_SETTING` if
    it is set to a number, else `DEFAULT_URGENT`."""
    try:
        value = taskwarrior.get(URGENT_SETTING)
        return float(value) if value is not None else DEFAULT_URGENT
    except (TaskwarriorError, ValueError):
        return DEFAULT_URGENT
