"""jiyuu's in-memory mind map: the node tree, and the ids its stored metadata is keyed by.

A map is a tree of `Node` objects reachable from one root. Everything a node carries beyond
its text and children — whether it is folded, which side of the root it is drawn on, whether
it is a task, and any other metadata attached to it — lives on the `Node` itself; nothing
here reads or writes a file.

Metadata kept separately from the tree, rather than inline in it, needs a key that survives
being written out and read back without depending on which Python object a node happens to
be. `node_id` computes that key from a node's `path`: the sequence of `(text, occurrence)`
pairs from the level below the root down to the node, where `occurrence` numbers same-text
siblings under one parent starting at 1. Two nodes with the same text and the same position
among same-text siblings get the same id on every read of the same tree; renaming or moving a
node changes its id, which is fine, since an id computed this way is meant to be dropped
harmlessly when it goes stale rather than kept in sync by hand.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Iterator

#: A node's position among its same-text siblings, as `[text, occurrence]` pairs from the
#: level below the root down to the node. Each pair is a list, not a tuple, so a path loaded
#: straight out of JSON needs no conversion before being passed to `node_id`.
NodePath = list[list[str | int]]

#: The priorities a task can have, highest first: taskwarrior's default `priority` values
#: (https://taskwarrior.org/docs/priority/).
PRIORITIES = ("H", "M", "L")


@dataclass(frozen=True)
class Task:
    """What makes a node a task: whether it is done, when it is due, and its priority.

    `due` is an ISO date, `"2026-10-25"`, or an ISO date and time to the minute,
    `"2026-10-25T14:00"`, in local time. `priority` is one of `PRIORITIES`. Either is `None`
    when not set. Frozen, so that a recorded `Task` can be kept as it is and put back later
    without being copied.
    """

    done: bool = False
    due: str | None = None
    priority: str | None = None


@dataclass(frozen=True)
class TaskLink:
    """The task in taskwarrior (https://taskwarrior.org) that a node's task is kept in.

    `uuid` is the taskwarrior task's uuid. `synced` is the time of the last sync, as
    taskwarrior's `modified` timestamp of the task at that moment (`"20261019T211745Z"`).
    `text` and `task` are the node's text and task as they were at that sync: comparing
    them with the node's current ones tells whether the node changed since.
    """

    uuid: str
    synced: str
    text: str
    task: Task


@dataclass(eq=False)
class Node:
    """One node of a mind map.

    Compared and hashed by identity, not by field values (`eq=False` leaves both as the
    default `object` behaviour). Two nodes can be entirely identical in text, folding and
    side — a second same-text sibling with no children of its own, say — and still need to
    be told apart by which object they are: by `walk`, `parent_of` and `path_of` below, and
    by any caller that keys a dictionary on a `Node`.
    """

    text: str
    children: list[Node] = field(default_factory=list)
    folded: bool = False
    #: `"left"`, `"right"`, or `None`. Only meaningful on a node whose parent is the root;
    #: `None` there means its side is undecided, not that it has none.
    side: str | None = None
    #: Set when this node is a task; `None` on a plain node. Never set on the root.
    task: Task | None = None
    #: The taskwarrior task this node was last synced with, if any. Kept when `task` is set
    #: back to `None`, so that the next sync can delete the taskwarrior task.
    task_link: TaskLink | None = None
    #: Metadata attached to this node that this module does not itself give a meaning to.
    extra: dict[str, str] = field(default_factory=dict)


@dataclass
class MindMap:
    """A loaded map: its tree, and whatever else was read alongside it.

    `meta` and `other_sections` exist so that data this module has no opinion about — a
    file's own header fields, or a part of it this module does not read — survives being
    loaded and saved again unchanged.
    """

    root: Node
    meta: dict[str, object] = field(default_factory=dict)
    other_sections: dict[str, str] = field(default_factory=dict)
    #: Links to taskwarrior tasks whose node is no longer in the tree: deleted, or renamed
    #: in a text editor so that its stored metadata no longer finds it. Kept until a sync
    #: has deleted their taskwarrior tasks.
    orphan_tasks: list[TaskLink] = field(default_factory=list)


def walk(root: Node) -> Iterator[Node]:
    """Every node under `root`, depth-first, in the order its children were written in.

    `root` itself is never yielded: a path is always relative to it, so `root` has no path
    of its own for `node_id` to be computed from.
    """
    for child in root.children:
        yield child
        yield from walk(child)


def depths(root: Node) -> dict[Node, int]:
    """Every node's distance from `root`: `0` for `root` itself, `1` for its children, and
    so on — folded or not."""
    result = {root: 0}
    pending = [root]
    while pending:
        node = pending.pop()
        for child in node.children:
            result[child] = result[node] + 1
            pending.append(child)
    return result


def descendant_count(node: Node) -> int:
    """How many nodes are under `node`, at any depth, not counting `node` itself."""
    return sum(1 for _ in walk(node))


def parent_of(node: Node, root: Node) -> Node | None:
    """The parent of `node` in the tree rooted at `root`, or `None` if `node` is `root`.

    Raises `ValueError` if `node` is neither `root` nor reachable from it, rather than
    answering `None` for that case too: a node that is not in the tree at all and the root
    of the tree are not the same thing, and conflating them would turn a caller's mistake
    into a wrong answer instead of an error.
    """
    if node is root:
        return None
    if node in root.children:
        return root
    for candidate in walk(root):
        if node in candidate.children:
            return candidate
    raise ValueError(f"{node!r} is not {root!r} and is not reachable from it")


def path_of(node: Node, root: Node) -> NodePath:
    """`node`'s path: `[text, occurrence]` for each ancestor from below `root` down to it.

    `occurrence` counts from 1 and is `node`'s position among its parent's children that
    share its exact text — so same-text siblings get different occurrences and so different
    ids, while a child whose text is unique among its siblings simply gets `occurrence = 1`.
    """
    chain: NodePath = []
    current = node
    while current is not root:
        parent = parent_of(current, root)
        assert parent is not None  # current is not root here, so parent_of cannot answer None
        same_text = [child for child in parent.children if child.text == current.text]
        chain.append([current.text, same_text.index(current) + 1])
        current = parent
    chain.reverse()
    return chain


def node_id(path: NodePath) -> str:
    """The id `path` is stored under: the first 16 hex characters of the `blake2b` digest of
    `path`, JSON-encoded.

    Encoding the whole path as one JSON value before hashing, rather than joining its parts
    with a separator, is what lets a node's text contain any character at all — a `/`, a
    `"`, a `#` — without the path needing an escaping rule of its own.
    """
    encoded = json.dumps(path, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.blake2b(encoded).hexdigest()[:16]
