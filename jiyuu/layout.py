"""Lays out a mind map's tree as boxes and edges in a 2D plane.

The root sits at the horizontal centre of the plane and splits its own children into two
independent columns, left and right; every other node keeps all of its children in one
column, on whichever side its ancestor is already on. A box's position comes from two passes
over the tree: a bottom-up pass measures how tall each subtree needs to be, and a top-down
pass places every node within the vertical span its parent's own pass reserved for it,
centred on that span. Neither pass knows about Flet, a file format, or anything outside this
plane.
"""

from __future__ import annotations

from dataclasses import dataclass

from .measure import Measurer
from .model import Node

#: `"left"` or `"right"`.
Side = str


@dataclass
class LayoutSettings:
    """Tunable spacing used throughout a layout pass, all in logical pixels."""

    #: Horizontal padding inside a node's own box, each side.
    pad_x: float = 16.0
    #: Vertical padding inside a node's own box, each side.
    pad_y: float = 8.0
    #: Vertical gap between two sibling subtrees stacked in the same column.
    vertical_gap: float = 12.0
    #: Horizontal gap between a parent's facing edge and its nearest child's edge.
    horizontal_gap: float = 48.0


@dataclass(frozen=True)
class Rect:
    """A node's box. `(x, y)` is its top-left corner."""

    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class Edge:
    """One edge drawn from `parent`'s box to `child`'s box, on `side` of the map."""

    parent: Node
    child: Node
    side: Side


@dataclass
class Plane:
    """Where a laid-out map sits on a drawing surface whose origin is its top-left corner.

    `layout` centres a map on `(0, 0)`, so about half of it has negative coordinates, while
    a drawing surface needs every box at a non-negative offset. `offset_x`/`offset_y` is
    added to every box; `width`/`height` is the surface size that then holds all of them.
    """

    offset_x: float = 0.0
    offset_y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    def fit(self, rects: dict[Node, Rect], margin: float) -> dict[Node, Rect]:
        """`rects` moved onto this plane, growing the plane if they do not fit it already.

        The offset and size only ever grow, never shrink: so folding a branch, which takes
        boxes away, leaves every remaining box where it was on the surface instead of
        moving the whole map to fill the space the branch used to take up.
        """
        self.offset_x = max(self.offset_x, margin - min(rect.x for rect in rects.values()))
        self.offset_y = max(self.offset_y, margin - min(rect.y for rect in rects.values()))
        moved = {
            node: Rect(rect.x + self.offset_x, rect.y + self.offset_y, rect.width, rect.height)
            for node, rect in rects.items()
        }
        self.width = max(self.width, max(rect.x + rect.width for rect in moved.values()) + margin)
        self.height = max(self.height, max(rect.y + rect.height for rect in moved.values()) + margin)
        return moved


def node_box_size(node: Node, measurer: Measurer, settings: LayoutSettings) -> tuple[float, float]:
    """A node's own box size: its text's size, plus padding on every side."""
    width, height = measurer.size_of(node.text)
    return (width + 2 * settings.pad_x, height + 2 * settings.pad_y)


# --- pass 1: bottom-up, heights only ----------------------------------------


def _column_height(nodes: list[Node], measurer: Measurer, settings: LayoutSettings) -> float:
    """The height a column of sibling subtrees needs: their own heights, plus a gap between
    each pair of them. Zero for an empty column, with no gap to account for."""
    if not nodes:
        return 0.0
    heights = [subtree_height(node, measurer, settings) for node in nodes]
    return sum(heights) + settings.vertical_gap * (len(heights) - 1)


def subtree_height(
    node: Node, measurer: Measurer, settings: LayoutSettings, *, is_root: bool = False
) -> float:
    """The height `node`'s whole subtree needs: at least its own box, and more if its
    visible children need more room than that.

    A folded node, or one with no children, needs only its own height: a folded node's
    hidden children are not part of what this reserves space for. The root is the one node
    whose children are not all in one column, so `is_root` measures one column per side
    instead of one column for all of `node.children` together.
    """
    _, own_height = node_box_size(node, measurer, settings)
    if node.folded or not node.children:
        return own_height
    if is_root:
        right = _column_height([c for c in node.children if c.side == "right"], measurer, settings)
        left = _column_height([c for c in node.children if c.side == "left"], measurer, settings)
        return max(own_height, right, left)
    return max(own_height, _column_height(node.children, measurer, settings))


def _resolve_sides(root: Node, measurer: Measurer, settings: LayoutSettings) -> None:
    """Assigns `"left"` or `"right"` to every one of `root`'s children that has no side yet.

    Processed in the order the children were written in: a child with a side already set
    keeps it, and still counts toward that side's running height, so a child decided after
    it balances against where that one actually ended up rather than against an empty
    column. A child with no side goes to whichever side currently has the smaller running
    height, right on a tie — so laying out several same-height children with none of them
    sided by hand simply alternates sides. The assignment is written onto `child.side`
    itself, which is what keeps a map's layout stable across repeated calls instead of being
    re-balanced from scratch, possibly differently, on every one of them.
    """
    right_total = 0.0
    left_total = 0.0
    for child in root.children:
        if child.side not in ("left", "right"):
            child.side = "right" if right_total <= left_total else "left"
        if child.side == "right":
            right_total += subtree_height(child, measurer, settings)
        else:
            left_total += subtree_height(child, measurer, settings)


# --- pass 2: top-down, assigning Rects --------------------------------------


def _place_column(
    nodes: list[Node],
    near_x: float,
    y_top: float,
    available_height: float,
    side: Side,
    *,
    measurer: Measurer,
    settings: LayoutSettings,
    out: dict[Node, Rect],
) -> None:
    """Places a column of sibling subtrees, stacked and centred within `available_height`."""
    if not nodes:
        return
    heights = [subtree_height(node, measurer, settings) for node in nodes]
    total = sum(heights) + settings.vertical_gap * (len(heights) - 1)
    y = y_top + (available_height - total) / 2
    for node, height in zip(nodes, heights):
        _place(node, near_x, y, height, side, measurer=measurer, settings=settings, out=out)
        y += height + settings.vertical_gap


def _place(
    node: Node,
    near_x: float,
    y_top: float,
    height_for_node: float,
    side: Side,
    *,
    measurer: Measurer,
    settings: LayoutSettings,
    out: dict[Node, Rect],
    is_root: bool = False,
) -> None:
    """Places `node` within the `height_for_node`-tall span starting at `y_top`, centred on
    it, then places its children in turn, if it has any that are visible.

    `near_x` is the edge of `node`'s own box nearest to its parent: for a right-side node,
    that is its left edge, so `near_x` becomes `x` directly; for a left-side node, that is
    its right edge, so `x` is `near_x` minus the box's own width. The root has no parent
    edge to measure from, and is instead centred on `x = 0`.
    """
    width, height = node_box_size(node, measurer, settings)
    y_center = y_top + height_for_node / 2
    if is_root:
        x = -width / 2
    elif side == "right":
        x = near_x
    else:
        x = near_x - width
    out[node] = Rect(x, y_center - height / 2, width, height)

    if node.folded or not node.children:
        return

    if is_root:
        _place_column(
            [c for c in node.children if c.side == "right"],
            x + width + settings.horizontal_gap, y_top, height_for_node, "right",
            measurer=measurer, settings=settings, out=out,
        )
        _place_column(
            [c for c in node.children if c.side == "left"],
            x - settings.horizontal_gap, y_top, height_for_node, "left",
            measurer=measurer, settings=settings, out=out,
        )
    else:
        child_near_x = (x + width + settings.horizontal_gap) if side == "right" else (x - settings.horizontal_gap)
        _place_column(
            node.children, child_near_x, y_top, height_for_node, side,
            measurer=measurer, settings=settings, out=out,
        )


def layout(
    root: Node, measurer: Measurer, settings: LayoutSettings | None = None
) -> tuple[dict[Node, Rect], list[Edge]]:
    """Lays out the whole map: a box for every visible node, and an edge for every visible
    parent-child pair.

    A node under a folded ancestor gets neither a box nor an edge: `folded` hides a subtree
    from the layout entirely, not just from being drawn, so a caller never has to filter
    hidden nodes out of the result itself.

    Resolves every one of `root`'s children's sides first (see `_resolve_sides`), so the two
    passes that follow, and the edges built from their result, all agree on where every
    first-level node ends up. The root's own box is centred on `(0, 0)`; everything else is
    placed outward from it, so the whole plane's vertical extent is centred on `y = 0` too.
    """
    settings = settings if settings is not None else LayoutSettings()
    _resolve_sides(root, measurer, settings)

    rects: dict[Node, Rect] = {}
    height = subtree_height(root, measurer, settings, is_root=True)
    _place(root, 0.0, -height / 2, height, "right", measurer=measurer, settings=settings, out=rects, is_root=True)

    edges = [
        Edge(parent=parent, child=child, side="right" if rects[child].x >= parent_rect.x else "left")
        for parent, parent_rect in rects.items()
        for child in parent.children
        if child in rects
    ]
    return rects, edges
