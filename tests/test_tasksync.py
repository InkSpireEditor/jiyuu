"""Tests for `jiyuu.tasksync`, against `FakeTaskwarrior`: each way a task can change, on
either side, and what a sync then does in taskwarrior and in the map."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from jiyuu import tasksync
from jiyuu.formats import mapfile
from jiyuu.model import MindMap, Node, Task, TaskLink
from jiyuu.taskwarrior import Taskwarrior, TaskwarriorError

from .stand_ins import FakeTaskwarrior

MAP = Path("/maps/example.ink")
#: Before every time the stand-in's clock gives, and after.
EARLY = datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
LATE = datetime(2026, 10, 21, 0, 0, tzinfo=UTC)


def _map() -> MindMap:
    """`Project`: `Goals` holding the tasks Foo (due, priority H) and Bar (done), and the
    plain node Baz holding the task Qux."""
    foo = Node(text="Foo", task=Task(due="2026-10-25", priority="H"))
    bar = Node(text="Bar", task=Task(done=True))
    qux = Node(text="Qux", task=Task())
    goals = Node(text="Goals", side="right", children=[foo, bar, Node(text="Baz", children=[qux])])
    return MindMap(root=Node(text="Project", children=[goals]))


def _find(mindmap: MindMap, text: str) -> Node:
    pending = [mindmap.root]
    while pending:
        node = pending.pop()
        if node.text == text:
            return node
        pending.extend(node.children)
    raise LookupError(text)


def _sync(mindmap: MindMap, tw: FakeTaskwarrior, map_time: datetime = EARLY) -> tasksync.SyncResult:
    return tasksync.sync(mindmap, cast(Taskwarrior, tw), MAP, map_time)


def _synced() -> tuple[MindMap, FakeTaskwarrior]:
    """The map synced once, and the taskwarrior it was synced with, its clock a second on."""
    mindmap, tw = _map(), FakeTaskwarrior()
    _sync(mindmap, tw)
    tw.tick()
    return mindmap, tw


def _task(mindmap: MindMap, tw: FakeTaskwarrior, text: str) -> dict:
    link = _find(mindmap, text).task_link
    assert link is not None
    return tw.tasks[link.uuid]


def test_a_first_sync_creates_every_task_and_links_its_node() -> None:
    mindmap, tw = _map(), FakeTaskwarrior()
    result = _sync(mindmap, tw)

    assert (result.created, result.sent, result.copied, result.deleted, result.changed) == (3, 0, 0, 0, True)
    foo = _task(mindmap, tw, "Foo")
    assert {k: foo[k] for k in ("description", "status", "due", "priority", "project", "jiyuumap")} == {
        "description": "Foo",
        "status": "pending",
        "due": "20261024T220000Z",  # local midnight, UTC+2 on that day here
        "priority": "H",
        "project": "example",
        "jiyuumap": "/maps/example.ink",
    }
    assert _task(mindmap, tw, "Bar")["status"] == "completed"
    link = _find(mindmap, "Foo").task_link
    assert link == TaskLink(foo["uuid"], foo["modified"], "Foo", Task(due="2026-10-25", priority="H"))
    assert tw.calls == ["export", "import", "export"]


def test_a_second_sync_with_nothing_changed_changes_nothing_anywhere() -> None:
    mindmap, tw = _synced()
    before = mapfile.dump(mindmap)
    result = _sync(mindmap, tw)
    assert not result.changed and mapfile.dump(mindmap) == before
    assert tw.imported[-1] == []  # every task was skipped
    assert (result.created, result.sent, result.copied, result.deleted) == (0, 0, 0, 0)


def test_the_uuid_of_a_new_task_comes_from_the_map_and_the_node() -> None:
    """The same map at the same path gives the same uuids; another path, others."""
    first, second = _map(), _map()
    _sync(first, FakeTaskwarrior())
    _sync(second, FakeTaskwarrior())
    other = _map()
    tasksync.sync(other, cast(Taskwarrior, FakeTaskwarrior()), Path("/maps/other.ink"), EARLY)
    uuid = cast(TaskLink, _find(first, "Foo").task_link).uuid
    assert uuid == cast(TaskLink, _find(second, "Foo").task_link).uuid
    assert uuid != cast(TaskLink, _find(other, "Foo").task_link).uuid


def test_a_sync_whose_map_was_not_saved_updates_the_same_tasks() -> None:
    """The map synced, then lost before it was saved: the next sync of the unsaved map
    finds the same tasks, keeps a tag added in taskwarrior since, and creates nothing."""
    tw = FakeTaskwarrior()
    _sync(_map(), tw)
    tw.tick()
    foo_uuid = next(u for u, task in tw.tasks.items() if task["description"] == "Foo")
    tw.edit(foo_uuid, tags=["home"])

    mindmap = _map()
    result = _sync(mindmap, tw)
    assert result.created == 0 and len(tw.tasks) == 3
    assert tw.tasks[foo_uuid]["tags"] == ["home"]
    assert cast(TaskLink, _find(mindmap, "Foo").task_link).uuid == foo_uuid


@pytest.mark.parametrize(
    ("text", "task", "expected"),
    [
        ("Food", Task(due="2026-10-25", priority="H"), {"description": "Food"}),
        ("Foo", Task(done=True, due="2026-10-25", priority="H"), {"status": "completed"}),
        ("Foo", Task(due="2026-10-26T14:30", priority="H"), {"due": "20261026T133000Z"}),  # UTC+1
        ("Foo", Task(priority="L"), {"due": None, "priority": "L"}),
        ("Foo", Task(), {"priority": None}),
    ],
    ids=["renamed", "ticked done", "due changed", "due removed", "priority removed"],
)
def test_a_change_made_in_the_map_is_sent_to_taskwarrior(text: str, task: Task, expected: dict) -> None:
    mindmap, tw = _synced()
    foo = _find(mindmap, "Foo")
    foo.text, foo.task = text, task
    result = _sync(mindmap, tw, LATE)

    stored = _task(mindmap, tw, text)
    for name, value in expected.items():
        assert stored.get(name) == value
    assert result.sent == 1 and result.changed  # the link records the new values
    assert cast(TaskLink, foo.task_link).task == task and cast(TaskLink, foo.task_link).text == text


def test_unticking_a_task_in_the_map_makes_it_pending_again() -> None:
    mindmap, tw = _synced()
    _find(mindmap, "Bar").task = Task()
    _sync(mindmap, tw, LATE)
    bar = _task(mindmap, tw, "Bar")
    assert bar["status"] == "pending" and "end" not in bar


@pytest.mark.parametrize(
    ("changes", "text", "task"),
    [
        ({"status": "completed"}, "Foo", Task(done=True, due="2026-10-25", priority="H")),
        ({"description": "Foo  renamed"}, "Foo renamed", Task(due="2026-10-25", priority="H")),
        ({"due": None, "priority": "M"}, "Foo", Task(priority="M")),
        ({"due": "20261025T120000Z"}, "Foo", Task(due="2026-10-25T13:00", priority="H")),  # UTC+1
    ],
    ids=["done", "renamed", "due removed and priority changed", "due with a time"],
)
def test_a_change_made_in_taskwarrior_is_copied_into_the_map(changes: dict, text: str, task: Task) -> None:
    mindmap, tw = _synced()
    tw.edit(cast(TaskLink, _find(mindmap, "Foo").task_link).uuid, **changes)
    result = _sync(mindmap, tw)
    foo = mindmap.root.children[0].children[0]
    assert (foo.text, foo.task) == (text, task)
    assert result.copied == 1 and result.changed


def test_a_change_made_in_taskwarrior_in_the_same_second_as_the_sync_is_copied() -> None:
    """`modified` counts whole seconds: an edit made in the second of the last sync has the
    link's own time, and is still found."""
    mindmap, tw = _map(), FakeTaskwarrior()
    _sync(mindmap, tw)
    tw.edit(cast(TaskLink, _find(mindmap, "Foo").task_link).uuid, status="completed")
    _sync(mindmap, tw)
    assert cast(Task, _find(mindmap, "Foo").task).done


@pytest.mark.parametrize(("map_time", "winner"), [(LATE, "map"), (EARLY, "taskwarrior")])
def test_a_task_changed_on_both_sides_takes_the_later_change(map_time: datetime, winner: str) -> None:
    mindmap, tw = _synced()
    foo = _find(mindmap, "Foo")
    tw.edit(cast(TaskLink, foo.task_link).uuid, priority="L")
    foo.task = Task(due="2026-10-25", priority="M")
    _sync(mindmap, tw, map_time)
    expected = "M" if winner == "map" else "L"
    assert foo.task.priority == expected
    assert _task(mindmap, tw, "Foo")["priority"] == expected


def test_a_task_deleted_in_taskwarrior_deletes_its_branch_and_the_tasks_in_it() -> None:
    """Baz is not a task; with Goals made one and deleted in taskwarrior, Goals goes, with
    Foo, Bar, Baz and Qux, whose tasks are deleted in taskwarrior too."""
    mindmap = _map()
    goals = mindmap.root.children[0]
    goals.task = Task()
    tw = FakeTaskwarrior()
    _sync(mindmap, tw)
    tw.tick()
    tw.edit(cast(TaskLink, goals.task_link).uuid, status="deleted")
    result = _sync(mindmap, tw)

    assert mindmap.root.children == [] and result.removed == [goals]
    assert {task["description"]: task["status"] for task in tw.tasks.values()} == {
        "Goals": "deleted", "Foo": "deleted", "Bar": "deleted", "Qux": "deleted",
    }
    assert result.deleted == 3


def test_a_node_made_plain_has_its_task_deleted_and_its_link_dropped() -> None:
    mindmap, tw = _synced()
    foo = _find(mindmap, "Foo")
    uuid = cast(TaskLink, foo.task_link).uuid
    foo.task = None
    result = _sync(mindmap, tw)
    assert tw.tasks[uuid]["status"] == "deleted" and foo.task_link is None
    assert result.deleted == 1 and result.changed and _find(mindmap, "Foo") is foo


def test_an_orphaned_link_has_its_task_deleted_and_is_dropped() -> None:
    mindmap, tw = _synced()
    goals = mindmap.root.children[0]
    foo = goals.children[0]
    goals.children.remove(foo)
    mindmap.orphan_tasks.append(cast(TaskLink, foo.task_link))
    result = _sync(mindmap, tw)
    assert tw.tasks[cast(TaskLink, foo.task_link).uuid]["status"] == "deleted"
    assert mindmap.orphan_tasks == [] and result.deleted == 1


def test_a_task_gone_from_taskwarrior_is_created_again_with_the_map_s_values() -> None:
    mindmap, tw = _synced()
    uuid = cast(TaskLink, _find(mindmap, "Foo").task_link).uuid
    del tw.tasks[uuid]
    result = _sync(mindmap, tw)
    assert result.created == 1 and tw.tasks[uuid]["description"] == "Foo"


def test_a_sync_keeps_what_taskwarrior_adds_to_a_task() -> None:
    mindmap, tw = _synced()
    uuid = cast(TaskLink, _find(mindmap, "Foo").task_link).uuid
    tw.edit(uuid, tags=["home"], annotations=[{"entry": tw.now, "description": "a note"}])
    _find(mindmap, "Foo").text = "Food"
    _sync(mindmap, tw, LATE)
    assert tw.tasks[uuid]["tags"] == ["home"] and tw.tasks[uuid]["annotations"][0]["description"] == "a note"


def test_a_moved_map_updates_the_project_and_path_of_its_tasks() -> None:
    mindmap, tw = _synced()
    tasksync.sync(mindmap, cast(Taskwarrior, tw), Path("/elsewhere/renamed.ink"), EARLY)
    foo = _task(mindmap, tw, "Foo")
    assert (foo["project"], foo["jiyuumap"]) == ("renamed", "/elsewhere/renamed.ink")


def test_urgency_is_reported_for_tasks_not_done() -> None:
    mindmap, tw = _synced()
    tw.urgency[cast(TaskLink, _find(mindmap, "Foo").task_link).uuid] = 12.5
    result = _sync(mindmap, tw)
    assert result.urgency == {_find(mindmap, "Foo"): 12.5, _find(mindmap, "Qux"): 1.0}


def test_a_failing_taskwarrior_leaves_the_map_as_it_was() -> None:
    mindmap, tw = _map(), FakeTaskwarrior()
    tw.failing = TaskwarriorError("task import: no")
    before = mapfile.dump(mindmap)
    with pytest.raises(TaskwarriorError):
        _sync(mindmap, tw)
    assert mapfile.dump(mindmap) == before


def test_apply_leaves_a_node_no_longer_in_the_tree_alone() -> None:
    """A result computed from a snapshot, applied after the node it updates was deleted."""
    mindmap, tw = _map(), FakeTaskwarrior()
    result = tasksync.run_sync(tasksync.snapshot(mindmap), cast(Taskwarrior, tw), MAP, EARLY)
    goals = mindmap.root.children[0]
    foo = goals.children[0]
    goals.children.remove(foo)
    tasksync.apply(mindmap, result)
    assert foo.task_link is None and _find(mindmap, "Bar").task_link is not None


@pytest.mark.parametrize(("setting", "threshold"), [(None, 9.0), ("12", 12.0), ("high", 9.0)])
def test_urgent_threshold(setting: str | None, threshold: float) -> None:
    tw = FakeTaskwarrior()
    if setting is not None:
        tw.settings["jiyuu.urgent"] = setting
    assert tasksync.urgent_threshold(cast(Taskwarrior, tw)) == threshold


def test_the_summary_names_each_count() -> None:
    result = tasksync.SyncResult(created=1, sent=2, copied=3, deleted=4, removed=[Node(text="x")])
    assert result.summary() == (
        "tasks: 1 created, 2 updated from the map, 3 updated from taskwarrior, "
        "4 deleted in taskwarrior, 1 nodes deleted from the map"
    )
