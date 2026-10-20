"""A map stored as an `.ink` file: `ink:meta`, the tree in `ink:body`, and per-node
metadata in `ink:nodes`.

    ===== ink:meta
    kind: mindmap
    ===== ink:body
    - Project
      - Goals
      - Risks
    ===== ink:nodes
    "7be48fc73f0ebe9c": {side: "right"}
    "32a21dfedf2cf99c": {side: "left", folded: "true"}

The file's sections are read by `ink`, its body by `body`. `ink:nodes` holds one line per
node that has anything to record, keyed by the node's id (`model.node_id` of its
`model.path_of`), in body order. Two keys mean something here:

- `side`: `"left"` or `"right"`, on a child of the root only. It is written for every child
  of the root whose side is decided, so reopening a file never depends on the layout
  deciding the sides again.
- `folded`: `"true"` on a folded node. An unfolded node has no `folded` key at all.

A node that is a task and has been synced with taskwarrior (https://taskwarrior.org) has
seven more keys, which record that sync (`model.TaskLink`):

    "a1f35c2e9b7d4f60": {kind: "task", uuid: "0b6c4e2a-5d1f-4c3e-9a7b-2f8e6d4c1a90",
      synced: "20261019T211745Z", text: "Foo", status: "pending", due: "2026-10-25",
      priority: "H"}

- `kind`: `"task"`.
- `uuid`: the taskwarrior task's uuid.
- `synced`: taskwarrior's `modified` timestamp of the task at the last sync.
- `text`, `status` (`"pending"` or `"done"`), `due`, `priority`: the node's text and task as
  they were at the last sync. `due` and `priority` are left out when they were not set. The
  node's current task is in the body (see `body`); these are only compared with it.

Any other key in an entry is kept on the node (`Node.extra`) and written back with it.

An entry whose key matches no node — the node was renamed or moved in a text editor since
the file was written — is not applied, and is not written again: the node it described
gets the defaults (unfolded, side decided by the layout). Nothing in the tree depends on
`ink:nodes`, so losing an entry this way never loses node text.

A task entry is the exception, since dropping it would lose which taskwarrior task the node
was synced with. It is attached to the first task in the body that has no entry of its own
and the same text as the entry's `text` — a task moved by hand keeps its text. If there is
none, it is kept in `MindMap.orphan_tasks`, reported as a problem, and written back keyed by
its uuid, which no node id can equal (an id has 16 characters, a uuid 36). An entry keyed by
its uuid is how a task whose node was deleted is written, and is not reported.

Every key and value in `ink:nodes` is written quoted, and read back with
`yaml.BaseLoader`, which reads every scalar as a string whether quoted or not. Some ids are
sixteen decimal digits (`"1984891675846323"`); a YAML loader that resolves scalars would
read such a key unquoted as an integer, which would then match no node.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..model import MindMap, Node, Task, TaskLink, node_id, path_of, walk
from . import body, ink
from .ink import WARNING, Problem

#: The `ink:meta` key and value that mark a `.ink` file as a map.
KIND_KEY = "kind"
KIND = "mindmap"
#: The `kind` of a task entry in `ink:nodes`.
TASK_KIND = "task"
#: The keys of a task entry, in the order they are written.
TASK_KEYS = ("kind", "uuid", "synced", "text", "status", "due", "priority")


def _fence_line_number(text: str, name: str) -> int:
    """The line number of the last fence opening section `name` in `text`, or `0` if no
    fence opens it. The last, because a section opened twice keeps its last occurrence."""
    numbers = [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if ink.section_name(line) == name
    ]
    return numbers[-1] if numbers else 0


def read_nodes_section(text: str) -> tuple[dict[str, dict[str, str]], list[Problem]]:
    """The entries in an `ink:nodes` section's `text`, by node id, and every problem found.

    Problems are numbered by line within `text`, from 1. Text that is not YAML, or not a
    mapping, gives no entries at all. An entry whose value is not a mapping, or a field
    whose value is not a single string, is left out and reported.
    """
    try:
        loaded = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if mark is not None else 1
        return {}, [Problem(line, WARNING, "the nodes section is not valid YAML; every node gets defaults")]
    if loaded is None:
        return {}, []
    if not isinstance(loaded, dict):
        return {}, [Problem(1, WARNING, "the nodes section is not a mapping; every node gets defaults")]

    entries: dict[str, dict[str, str]] = {}
    problems: list[Problem] = []
    for key, fields in loaded.items():
        if not isinstance(fields, dict):
            problems.append(Problem(1, WARNING, f"the nodes entry {key!r} is not a mapping; ignored"))
            continue
        kept = {name: value for name, value in fields.items() if isinstance(value, str)}
        for name in fields.keys() - kept.keys():
            problems.append(
                Problem(1, WARNING, f"the field {name!r} of nodes entry {key!r} is not a string; ignored")
            )
        entries[key] = kept
    return entries, problems


def render_nodes_section(entries: dict[str, dict[str, str]]) -> str:
    """`entries` as the text of an `ink:nodes` section: one line per entry, in the order
    given, every key and value quoted by `json.dumps`, which YAML reads as a quoted string."""
    lines = []
    for key, fields in entries.items():
        mapping = ", ".join(f"{name}: {json.dumps(value)}" for name, value in fields.items())
        lines.append(f"{json.dumps(key)}: {{{mapping}}}\n")
    return "".join(lines)


def read_task_link(fields: dict[str, str]) -> TaskLink | None:
    """The task link an `ink:nodes` entry's `fields` record, or `None` if they are not a
    task entry, or have no `uuid` or no `synced`."""
    if fields.get("kind") != TASK_KIND or not fields.get("uuid") or not fields.get("synced"):
        return None
    task = Task(
        done=fields.get("status") == "done",
        due=fields.get("due") or None,
        priority=fields.get("priority") or None,
    )
    return TaskLink(uuid=fields["uuid"], synced=fields["synced"], text=fields.get("text", ""), task=task)


def task_link_fields(link: TaskLink) -> dict[str, str]:
    """`link` as the fields of an `ink:nodes` entry, in `TASK_KEYS` order."""
    fields = {
        "kind": TASK_KIND,
        "uuid": link.uuid,
        "synced": link.synced,
        "text": link.text,
        "status": "done" if link.task.done else "pending",
    }
    if link.task.due:
        fields["due"] = link.task.due
    if link.task.priority:
        fields["priority"] = link.task.priority
    return fields


def apply_nodes_section(root: Node, entries: dict[str, dict[str, str]]) -> tuple[list[TaskLink], list[Problem]]:
    """Sets every node under `root` from its entry in `entries`, or to the defaults if it
    has none; returns the task links whose node was not found, and a problem for each one
    keyed by a node id rather than by its uuid.

    A `side` other than `"left"` or `"right"` is read as undecided, as if it were absent. A
    task entry with no `uuid` or no `synced` is reported, and its keys are dropped.
    """
    problems: list[Problem] = []
    applied: set[str] = set()
    for node in walk(root):
        key = node_id(path_of(node, root))
        fields = entries.get(key, {})
        if key in entries:
            applied.add(key)
        side = fields.get("side")
        node.side = side if side in ("left", "right") else None
        node.folded = fields.get("folded") == "true"
        node.task_link = read_task_link(fields)
        task_keys = TASK_KEYS if fields.get("kind") == TASK_KIND else ()
        if task_keys and node.task_link is None:
            problems.append(Problem(1, WARNING, f"the task entry {key!r} has no uuid or no synced; ignored"))
        node.extra = {
            name: value for name, value in fields.items() if name not in ("side", "folded", *task_keys)
        }

    orphans: list[TaskLink] = []
    for key, fields in entries.items():
        link = read_task_link(fields) if key not in applied else None
        if link is None:
            continue
        unlinked = (n for n in walk(root) if n.task is not None and n.task_link is None and n.text == link.text)
        node = next(unlinked, None)
        if node is not None:
            node.task_link = link
            continue
        orphans.append(link)
        if key != link.uuid:
            problems.append(Problem(1, WARNING, f"the task entry for {link.text!r} matches no task in the body"))
    return orphans, problems


def build_nodes_section(root: Node, orphan_tasks: list[TaskLink] | None = None) -> dict[str, dict[str, str]]:
    """The `ink:nodes` entries for every node under `root` that has anything to record, in
    body order, keyed by node id; then one for each of `orphan_tasks`, keyed by its uuid."""
    entries: dict[str, dict[str, str]] = {}
    for node in walk(root):
        fields = dict(node.extra)
        if node in root.children and node.side is not None:
            fields["side"] = node.side
        if node.folded:
            fields["folded"] = "true"
        if node.task_link is not None:
            fields.update(task_link_fields(node.task_link))
        if fields:
            entries[node_id(path_of(node, root))] = fields
    for link in orphan_tasks or []:
        entries[link.uuid] = task_link_fields(link)
    return entries


def _kind_problems(text: str, document: ink.Document) -> list[Problem]:
    """A warning when `text` is not marked as a map: its `kind` names something else, or it
    has no fences at all and so no `meta` to say what it is."""
    kind = document.metadata.get(KIND_KEY)
    if kind is not None and kind != KIND:
        return [Problem(1, WARNING, f"ink:meta says kind: {kind}, not {KIND}; read as a map anyway")]
    if kind is None and document.body == text:
        return [Problem(1, WARNING, f"no ink:meta '{KIND_KEY}: {KIND}'; read as a map anyway")]
    return []


def read(text: str) -> tuple[MindMap | None, list[Problem]]:
    """The map in `.ink` file `text`, and every problem found reading it.

    The tree comes from the body, with each node's folding, side, task link and other
    fields from `ink:nodes`, and the task links whose node was not found in
    `MindMap.orphan_tasks`. `meta` becomes `MindMap.meta`, with `kind: mindmap` added if
    missing, and every section other than `body` and `nodes` is kept as text, to be written
    back as it was. Problems with the sections, the body and `ink:nodes` are numbered by line in the
    whole file, in line order. The map is `None` only when the body holds no tree.
    """
    document = ink.parse(text)
    root, body_problems = body.read(document.body)
    body_offset = 0 if document.body == text else _fence_line_number(text, ink.SECTION_BODY)
    problems = ink.check(text) + _kind_problems(text, document)
    problems += [Problem(p.line + body_offset, p.level, p.message) for p in body_problems]

    orphans: list[TaskLink] = []
    if root is not None:
        entries, nodes_problems = read_nodes_section(document.sections.get(ink.SECTION_NODES, ""))
        orphans, apply_problems = apply_nodes_section(root, entries)
        nodes_offset = _fence_line_number(text, ink.SECTION_NODES)
        problems += [Problem(p.line + nodes_offset, p.level, p.message) for p in nodes_problems + apply_problems]

    problems.sort(key=lambda problem: (problem.line, problem.level))
    if root is None:
        return None, problems
    meta = dict(document.metadata)
    meta.setdefault(KIND_KEY, KIND)
    other = {name: section for name, section in document.sections.items() if name != ink.SECTION_NODES}
    return MindMap(root=root, meta=meta, other_sections=other, orphan_tasks=orphans), problems


def load(path: Path) -> tuple[MindMap | None, list[Problem]]:
    """The map in the `.ink` file at `path`; see `read`. Raises `OSError` or
    `UnicodeDecodeError` if the file cannot be read as UTF-8 text."""
    return read(path.read_text(encoding="utf-8"))


def dump(mindmap: MindMap) -> str:
    """`mindmap` as the text of an `.ink` file: `meta` (with `kind: mindmap` added if
    missing), the tree as the body, every other section it was read with, and last
    `ink:nodes`, left out when no node has anything to record."""
    meta = dict(mindmap.meta)
    meta.setdefault(KIND_KEY, KIND)
    sections = dict(mindmap.other_sections)
    nodes_text = render_nodes_section(build_nodes_section(mindmap.root, mindmap.orphan_tasks))
    if nodes_text:
        sections[ink.SECTION_NODES] = nodes_text
    return ink.render(meta, body.write(mindmap.root), sections)
