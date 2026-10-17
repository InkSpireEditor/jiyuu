"""Turns a laid-out map into Flet controls: node boxes, fold markers, and the edges.

Every box is one `Container` at its `Rect`, stacked over a single `Canvas` holding every
edge as a cubic Bézier curve. Every colour comes from the `Theme` passed in. Nothing here
keeps state between calls: the window rebuilds the whole list each time the map changes,
which is fast enough for the map sizes jiyuu is meant for.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
import flet.canvas as cv

from ..layout import Edge, LayoutSettings, Rect
from ..measure import DEFAULT_FONT_SIZE
from ..model import Node, descendant_count
from ..theme import Theme

#: The family name the bundled font is registered under on the page.
FONT_FAMILY = "DejaVu Sans"
#: A fold marker is a circle this many pixels across, just outside its node's box.
MARKER_SIZE = 18.0
#: Gap between a node's box and its fold marker.
MARKER_GAP = 2.0
CORNER_RADIUS = 6
EDGE_WIDTH = 2


def edge_path(edge: Edge, rects: dict[Node, Rect], settings: LayoutSettings, color: str) -> cv.Path:
    """One edge as a cubic Bézier curve from the parent's facing edge to the child's near
    edge, bulging horizontally by half of the gap the layout left between them."""
    parent, child = rects[edge.parent], rects[edge.child]
    if edge.side == "right":
        start = (parent.x + parent.width, parent.y + parent.height / 2)
        end = (child.x, child.y + child.height / 2)
        bulge = settings.horizontal_gap / 2
    else:
        start = (parent.x, parent.y + parent.height / 2)
        end = (child.x + child.width, child.y + child.height / 2)
        bulge = -settings.horizontal_gap / 2
    return cv.Path(
        [
            cv.Path.MoveTo(*start),
            cv.Path.CubicTo(start[0] + bulge, start[1], end[0] - bulge, end[1], *end),
        ],
        paint=ft.Paint(color=color, style=ft.PaintingStyle.STROKE, stroke_width=EDGE_WIDTH),
    )


def node_box(
    node: Node,
    rect: Rect,
    depth: int,
    theme: Theme,
    *,
    selected: bool = False,
    on_click: Callable[[], None] | None = None,
) -> ft.Container:
    """A node's box, with its text centred, in its depth's colours from `theme` — or in the
    theme's selection colours if it is the selected node."""
    colors = theme.selection if selected else theme.for_depth(depth)
    return ft.Container(
        content=ft.Text(node.text, font_family=FONT_FAMILY, size=DEFAULT_FONT_SIZE, color=colors.text),
        left=rect.x,
        top=rect.y,
        width=rect.width,
        height=rect.height,
        bgcolor=colors.background,
        border=ft.Border.all(1, theme.edge),
        border_radius=CORNER_RADIUS,
        alignment=ft.Alignment.CENTER,
        on_click=(lambda _: on_click()) if on_click is not None else None,
    )


def fold_marker(node: Node, rect: Rect, side: str, theme: Theme, on_click: Callable[[], None]) -> ft.Container:
    """The circle on the outer side of a node with children, which folds or unfolds it.

    Empty while the node is unfolded; while it is folded, it shows how many nodes the fold
    hides, at any depth, so a folded branch's size can be seen without opening it.
    """
    x = rect.x + rect.width + MARKER_GAP if side == "right" else rect.x - MARKER_GAP - MARKER_SIZE
    hidden = str(descendant_count(node)) if node.folded else ""
    return ft.Container(
        content=ft.Text(hidden, font_family=FONT_FAMILY, size=10, color=theme.canvas),
        left=x,
        top=rect.y + (rect.height - MARKER_SIZE) / 2,
        width=MARKER_SIZE,
        height=MARKER_SIZE,
        bgcolor=theme.edge,
        shape=ft.BoxShape.CIRCLE,
        alignment=ft.Alignment.CENTER,
        on_click=lambda _: on_click(),
    )


def map_controls(
    root: Node,
    rects: dict[Node, Rect],
    edges: list[Edge],
    *,
    depths: dict[Node, int],
    theme: Theme,
    settings: LayoutSettings,
    size: tuple[float, float],
    on_toggle_fold: Callable[[Node], None],
    selected: Node | None = None,
    on_select: Callable[[Node], None] | None = None,
) -> list[ft.Control]:
    """Every control the map is drawn with, bottom to top: the edges' canvas, then each
    node's box, then each fold marker.

    `rects` must already be placed on the drawing surface (see `layout.Plane`); `size` is
    that surface's width and height. The root gets no fold marker: folding it would hide
    the whole map. `selected` is drawn in the theme's selection colours; clicking any box
    calls `on_select` with its node.
    """
    sides = {edge.child: edge.side for edge in edges}
    canvas = cv.Canvas(
        [edge_path(edge, rects, settings, theme.edge) for edge in edges],
        width=size[0],
        height=size[1],
    )
    boxes = [
        node_box(
            node,
            rect,
            depths[node],
            theme,
            selected=node is selected,
            on_click=(lambda node=node: on_select(node)) if on_select is not None else None,
        )
        for node, rect in rects.items()
    ]
    markers = [
        fold_marker(node, rect, sides[node], theme, lambda node=node: on_toggle_fold(node))
        for node, rect in rects.items()
        if node.children and node is not root
    ]
    return [canvas, *boxes, *markers]
