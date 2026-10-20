"""Changing a map's tree: adding, deleting, renaming, moving, folding and re-siding nodes,
with undo.

An `Editor` holds one tree. Each of its commands takes the selected node, changes the tree
in place, and returns the node to select afterwards. A command that would change nothing —
deleting the root, moving the first sibling up — returns the node it was given and records
nothing to undo.

The root's children are split between its two sides, and each side is shown as its own
column. Among them, a node's siblings are only those on its own side: moving a node up or
down swaps it with its neighbour on the same side, and deleting one selects a neighbour on
the same side. A new sibling of a first-level node goes on that node's side, and a node
promoted to the first level goes on the side of the node it came out of.

Undo restores the tree onto the very `Node` objects it was made of, rather than swapping in
a copy of it: before each command, every node's text, folding, side, task, task link and
list of children is recorded, along with the map's list of orphaned task links, and undoing
writes those values back. A node that a command removed is still
referenced by that record, so undoing brings the same object back. A caller that keeps
something per `Node` object, such as the shapes a window draws each node with, can
therefore keep it across an undo.

Deleting a branch that holds tasks synced with taskwarrior moves their task links to the
map's orphaned task links (`MindMap.orphan_tasks`): the nodes are no longer in the tree, so
the links would otherwise be lost at the next save, and a sync could not delete the tasks.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Node, Task, TaskLink, parent_of, walk

#: How many commands can be undone; the oldest is dropped first.
UNDO_LIMIT = 100

#: One node's recorded values: the node, its text, folded, side, task, task link, and a copy
#: of its children.
_NodeState = tuple[Node, str, bool, str | None, Task | None, TaskLink | None, list[Node]]


@dataclass
class _State:
    """Every node's recorded values, and a copy of the orphaned task links."""

    nodes: list[_NodeState]
    orphan_tasks: list[TaskLink]


@dataclass
class UndoEntry:
    """A recorded state of the tree, and the selection on each side of the change it
    undoes: `before` is selected when the tree is put back in this state, `after` when the
    change is made again."""

    state: _State
    before: Node
    after: Node


class Editor:
    """The commands that change one tree, and their undo and redo stacks."""

    def __init__(self, root: Node, orphan_tasks: list[TaskLink] | None = None) -> None:
        self.root = root
        #: The map's orphaned task links (`MindMap.orphan_tasks`), changed in place.
        self.orphan_tasks = orphan_tasks if orphan_tasks is not None else []
        #: Changes that can be undone, the latest last.
        self.undo_stack: list[UndoEntry] = []
        #: Changes undone that can be made again, the latest undone last. Emptied by any
        #: new command.
        self.redo_stack: list[UndoEntry] = []
        #: Counts every change made to the tree by a command, an undo or a redo, so that a
        #: caller can tell whether a call changed anything.
        self.version = 0

    def add_child(self, node: Node) -> Node:
        """Adds an empty node as `node`'s last child, unfolding `node` so that it is shown;
        returns the new node.

        A new child of the root has no side yet; the layout gives it one (see
        `layout.resolve_sides`).
        """
        state = self._capture()
        child = Node(text="")
        node.children.append(child)
        node.folded = False
        return self._record(state, node, child)

    def add_sibling(self, node: Node) -> Node:
        """Adds an empty node right after `node` among its parent's children, on `node`'s
        side if `node` is first-level; returns the new node. On the root, which has no
        siblings, adds a child instead."""
        if node is self.root:
            return self.add_child(node)
        parent = self._parent(node)
        state = self._capture()
        sibling = Node(text="", side=node.side if parent is self.root else None)
        parent.children.insert(parent.children.index(node) + 1, sibling)
        return self._record(state, node, sibling)

    def delete(self, node: Node) -> Node:
        """Removes `node` and everything under it; returns its previous sibling, else its
        next sibling, else its parent. The root cannot be deleted. The task links in the
        branch are added to `orphan_tasks`."""
        if node is self.root:
            return node
        parent = self._parent(node)
        row = self._row(node, parent)
        index = row.index(node)
        if index > 0:
            selected = row[index - 1]
        elif index + 1 < len(row):
            selected = row[index + 1]
        else:
            selected = parent
        state = self._capture()
        parent.children.remove(node)
        self.orphan_tasks.extend(n.task_link for n in (node, *walk(node)) if n.task_link is not None)
        return self._record(state, node, selected)

    def rename(self, node: Node, text: str) -> Node:
        """Sets `node`'s text to `text`, without its leading and trailing whitespace; returns
        `node`. Does nothing if that is already its text.

        The whitespace is dropped because a map file stores each node's text on one line
        and reads it back without it (see `jiyuu.formats.body`).
        """
        text = text.strip()
        if text == node.text:
            return node
        state = self._capture()
        node.text = text
        return self._record(state, node, node)

    def move_up(self, node: Node) -> Node:
        """Swaps `node` with its previous sibling; returns `node`. Does nothing to the first."""
        return self._move(node, -1)

    def move_down(self, node: Node) -> Node:
        """Swaps `node` with its next sibling; returns `node`. Does nothing to the last."""
        return self._move(node, 1)

    def promote(self, node: Node) -> Node:
        """Moves `node` out of its parent's children and into its grandparent's, right after
        its former parent; returns `node`. Does nothing to the root or a first-level node."""
        if node is self.root:
            return node
        parent = self._parent(node)
        if parent is self.root:
            return node
        grandparent = self._parent(parent)
        state = self._capture()
        parent.children.remove(node)
        grandparent.children.insert(grandparent.children.index(parent) + 1, node)
        if grandparent is self.root:
            node.side = parent.side
        return self._record(state, node, node)

    def toggle_fold(self, node: Node) -> Node:
        """Folds `node` if it is unfolded, unfolds it otherwise; returns `node`. Does nothing
        to a node with no children."""
        if not node.children:
            return node
        state = self._capture()
        node.folded = not node.folded
        return self._record(state, node, node)

    def set_side(self, node: Node, side: str) -> Node:
        """Puts first-level `node` on `side` (`"left"` or `"right"`) of the root; returns
        `node`. Does nothing to any other node, or if `node` is already on `side`."""
        if side not in ("left", "right"):
            raise ValueError(f"side must be 'left' or 'right', not {side!r}")
        if node is self.root or node not in self.root.children or node.side == side:
            return node
        state = self._capture()
        node.side = side
        return self._record(state, node, node)

    def undo(self) -> Node | None:
        """Puts the tree back as it was before the latest change still in effect; returns
        the node that was selected then, or `None` if there is nothing to undo."""
        if not self.undo_stack:
            return None
        entry = self.undo_stack.pop()
        self.redo_stack.append(UndoEntry(self._capture(), entry.before, entry.after))
        self._restore(entry.state)
        return entry.before

    def redo(self) -> Node | None:
        """Makes the latest undone change again; returns the node it selected, or `None` if
        there is nothing to redo."""
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        self.undo_stack.append(UndoEntry(self._capture(), entry.before, entry.after))
        self._restore(entry.state)
        return entry.after

    def _move(self, node: Node, step: int) -> Node:
        """Swaps `node` with the sibling `step` places from it (`-1` or `1`), if there is one."""
        if node is self.root:
            return node
        parent = self._parent(node)
        row = self._row(node, parent)
        index = row.index(node) + step
        if not 0 <= index < len(row):
            return node
        state = self._capture()
        children = parent.children
        here, there = children.index(node), children.index(row[index])
        children[here], children[there] = children[there], children[here]
        return self._record(state, node, node)

    def _parent(self, node: Node) -> Node:
        """`node`'s parent; `node` must not be the root."""
        parent = parent_of(node, self.root)
        assert parent is not None  # only the root has no parent
        return parent

    def _row(self, node: Node, parent: Node) -> list[Node]:
        """`node` and its siblings, in order: for a first-level node, only those on its side."""
        if parent is self.root:
            return [child for child in parent.children if child.side == node.side]
        return parent.children

    def _capture(self) -> _State:
        """Every node's current values, the root's included, and the orphaned task links."""
        nodes = [
            (node, node.text, node.folded, node.side, node.task, node.task_link, list(node.children))
            for node in (self.root, *walk(self.root))
        ]
        return _State(nodes, list(self.orphan_tasks))

    def _restore(self, state: _State) -> None:
        """Writes the values in `state` back onto their nodes and the orphaned task links."""
        for node, text, folded, side, task, task_link, children in state.nodes:
            node.text, node.folded, node.side = text, folded, side
            node.task, node.task_link = task, task_link
            node.children = list(children)
        self.orphan_tasks[:] = state.orphan_tasks
        self.version += 1

    def _record(self, state: _State, before: Node, after: Node) -> Node:
        """Records a change just made, from `state`, as one that can be undone; returns
        `after`."""
        self.undo_stack.append(UndoEntry(state, before, after))
        del self.undo_stack[:-UNDO_LIMIT]
        self.redo_stack.clear()
        self.version += 1
        return after
