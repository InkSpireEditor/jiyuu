"""Moving the selection around a map with the arrow keys, as FreeMind does.

Right and Left move away from the root or back towards it, which way being which depending
on the side of the map the selection is on: on the right side, Right goes to a child and
Left to the parent; on the left side, the reverse. From the root, Right and Left go into the
right and left side respectively. Up and Down move between siblings — on the root's own
children, only between those on the same side — and do nothing past the first or last.
Home goes back to the root.

Moving into a node's children picks the child the selection last came back out of, if
there is one, otherwise the middle child, so that going out and back in returns to the
same place rather than always to the first child. A folded node's children cannot be
entered, since they are not shown.
"""

from __future__ import annotations

from .model import Node, parent_of, walk

RIGHT = "right"
LEFT = "left"
UP = "up"
DOWN = "down"
HOME = "home"


class Navigator:
    """Selection movement over one map, remembering which child each node was last left
    from."""

    def __init__(self, root: Node) -> None:
        self.root = root
        #: The child last moved back out of, per `(parent, side)`. `side` is only set for
        #: the root, whose two sides are entered separately; it is `None` for every other
        #: node.
        self._last_left: dict[tuple[Node, str | None], Node] = {}

    def side_of(self, node: Node) -> str | None:
        """The side of the map `node` is on — its first-level ancestor's side — or `None`
        for the root itself."""
        if node is self.root:
            return None
        current = node
        parent = parent_of(current, self.root)
        while parent is not self.root:
            assert parent is not None  # only the root has no parent
            current = parent
            parent = parent_of(current, self.root)
        return current.side

    def _children(self, node: Node, side: str | None) -> list[Node]:
        """`node`'s shown children: none if it is folded, and for the root only those on
        `side`."""
        if node.folded:
            return []
        if node is self.root:
            return [child for child in node.children if child.side == side]
        return list(node.children)

    def _enter(self, node: Node, side: str | None) -> Node:
        """The child moving into `node` selects, or `node` itself if it has none shown."""
        children = self._children(node, side)
        if not children:
            return node
        remembered = self._last_left.get((node, side))
        if remembered in children:
            return remembered
        return children[len(children) // 2]

    def move(self, selected: Node, key: str) -> Node:
        """The node selected after pressing `key` (one of `RIGHT`, `LEFT`, `UP`, `DOWN`,
        `HOME`) with `selected` selected. Returns `selected` itself where `key` leads
        nowhere."""
        if key == HOME:
            return self.root
        if selected is self.root:
            return self._enter(self.root, key) if key in (RIGHT, LEFT) else selected

        side = self.side_of(selected)
        parent = parent_of(selected, self.root)
        assert parent is not None  # `selected` is not the root
        parent_side = side if parent is self.root else None
        outward = side
        inward = LEFT if side == RIGHT else RIGHT

        if key == outward:
            return self._enter(selected, None)
        if key == inward:
            self._last_left[(parent, parent_side)] = selected
            return parent
        if key in (UP, DOWN):
            siblings = self._children(parent, parent_side)
            index = siblings.index(selected) + (-1 if key == UP else 1)
            return siblings[index] if 0 <= index < len(siblings) else selected
        return selected


def is_inside(node: Node, ancestor: Node) -> bool:
    """Whether `node` is somewhere under `ancestor`, at any depth (not `ancestor` itself)."""
    return any(descendant is node for descendant in walk(ancestor))
