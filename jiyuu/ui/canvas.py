"""Turns a laid-out map into Flet controls: node boxes, fold markers, and the edges.

Every box is one `Container` at its `Rect`, stacked over a single `Canvas` holding every
edge as a cubic Bézier curve. Every colour comes from the `Theme` passed in.

`MapDrawing` keeps the control it made for each node and reuses it on every later redraw,
changing only its position, size, text, colours and visibility. A node hidden by a fold keeps
its controls in the drawing, made invisible, rather than having them taken out. Flet sends a
control's property to the window only when its value changed, but sends a whole control
every time it is added to the drawing again; so folding or unfolding a branch of a map of
several hundred nodes sends which boxes appeared, disappeared or moved, rather than every
box in the branch.
"""

from __future__ import annotations

from collections.abc import Callable

import flet as ft
import flet.canvas as cv

from ..layout import Edge, LayoutSettings, Rect
from ..measure import DEFAULT_FONT_SIZE
from ..model import Node, depths, descendant_count
from ..theme import Colors, Theme

#: The family name the bundled font is registered under on the page.
FONT_FAMILY = "DejaVu Sans"
#: A fold marker is a circle this many pixels across, just outside its node's box.
MARKER_SIZE = 18.0
#: Gap between a node's box and its fold marker.
MARKER_GAP = 2.0
CORNER_RADIUS = 6
EDGE_WIDTH = 2


def edge_elements(edge: Edge, rects: dict[Node, Rect], settings: LayoutSettings) -> list[cv.Path.PathElement]:
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
    return [
        cv.Path.MoveTo(*start),
        cv.Path.CubicTo(start[0] + bulge, start[1], end[0] - bulge, end[1], *end),
    ]


class MapDrawing:
    """The controls a map is drawn with, kept from one redraw to the next.

    A node's box, fold marker and the edge leading to it are made the first time the node
    is visible, and kept, keyed by the node, while it stays in the tree. While a fold hides
    the node, its box and marker are invisible and its edge has no elements, so nothing of
    it is drawn.
    """

    def __init__(
        self,
        theme: Theme,
        settings: LayoutSettings,
        *,
        on_select: Callable[[Node], None],
        on_toggle_fold: Callable[[Node], None],
    ) -> None:
        self.theme = theme
        self.settings = settings
        self.on_select = on_select
        self.on_toggle_fold = on_toggle_fold
        #: The one canvas every edge is drawn on, under every box.
        self.canvas = cv.Canvas()
        self._boxes: dict[Node, ft.Container] = {}
        self._markers: dict[Node, ft.Container] = {}
        #: Each edge's path, keyed by the edge's child: a node has one edge leading to it.
        self._paths: dict[Node, cv.Path] = {}
        self._depths: dict[Node, int] = {}

    def draw(
        self,
        root: Node,
        rects: dict[Node, Rect],
        edges: list[Edge],
        size: tuple[float, float],
        selected: Node | None = None,
    ) -> list[ft.Control]:
        """Every control the map is drawn with, bottom to top: the edges' canvas, then each
        node's box, then each fold marker, for every node visible now or at any earlier
        draw that is still in the tree. Only the nodes in `rects` are visible.

        `rects` must already be placed on the drawing surface (see `layout.Plane`); `size` is
        that surface's width and height. The root gets no fold marker: folding it would hide
        the whole map. `selected` is drawn in the theme's selection colours.
        """
        self._depths = depths(root)
        for kept in (self._boxes, self._markers, self._paths):
            for node in [node for node in kept if node not in self._depths]:
                del kept[node]

        self.canvas.width, self.canvas.height = size
        for edge in edges:
            self._path(edge, rects)
        sides = {edge.child: edge.side for edge in edges}
        for node, rect in rects.items():
            self._box(node, rect, node is selected)
            if node.children and node is not root:
                self._marker(node, rect, sides[node])
            elif node in self._markers:
                self._markers[node].visible = False

        for node, path in self._paths.items():
            if node not in rects:
                path.elements = []
        for kept in (self._boxes, self._markers):
            for node, control in kept.items():
                if node not in rects:
                    control.visible = False

        self.canvas.shapes = list(self._paths.values())
        return [self.canvas, *self._boxes.values(), *self._markers.values()]

    def set_selected(self, previous: Node | None, selected: Node) -> list[ft.Control]:
        """Recolours `previous`'s box back to its depth's colours and `selected`'s in the
        theme's selection colours, leaving every other control as it was; returns the boxes
        recoloured."""
        recoloured: list[ft.Control] = []
        if previous is not None and previous in self._boxes:
            self._colour(self._boxes[previous], self.theme.for_depth(self._depths[previous]))
            recoloured.append(self._boxes[previous])
        self._colour(self._boxes[selected], self.theme.selection)
        recoloured.append(self._boxes[selected])
        return recoloured

    def _path(self, edge: Edge, rects: dict[Node, Rect]) -> None:
        """Makes `edge`'s path if new, and sets it to follow the edge's current endpoints."""
        elements = edge_elements(edge, rects, self.settings)
        path = self._paths.get(edge.child)
        if path is None:
            path = self._paths[edge.child] = cv.Path(
                elements,
                paint=ft.Paint(color=self.theme.edge, style=ft.PaintingStyle.STROKE, stroke_width=EDGE_WIDTH),
            )
        path.elements = elements

    def _box(self, node: Node, rect: Rect, selected: bool) -> ft.Container:
        """`node`'s kept box, made if new, at `rect` and in its current colours."""
        box = self._boxes.get(node)
        if box is None:
            box = self._boxes[node] = ft.Container(
                content=ft.Text(font_family=FONT_FAMILY, size=DEFAULT_FONT_SIZE),
                border=ft.Border.all(1, self.theme.edge),
                border_radius=CORNER_RADIUS,
                alignment=ft.Alignment.CENTER,
                on_click=lambda _: self.on_select(node),
            )
        box.visible = True
        box.left, box.top, box.width, box.height = rect.x, rect.y, rect.width, rect.height
        _text(box).value = node.text
        self._colour(box, self.theme.selection if selected else self.theme.for_depth(self._depths[node]))
        return box

    def _marker(self, node: Node, rect: Rect, side: str) -> ft.Container:
        """`node`'s kept fold marker, made if new: the circle on the outer side of a node
        with children, which folds or unfolds it.

        Empty while the node is unfolded; while it is folded, it shows how many nodes the
        fold hides, at any depth, so a folded branch's size can be seen without opening it.
        """
        marker = self._markers.get(node)
        if marker is None:
            marker = self._markers[node] = ft.Container(
                content=ft.Text(font_family=FONT_FAMILY, size=10, color=self.theme.canvas),
                width=MARKER_SIZE,
                height=MARKER_SIZE,
                bgcolor=self.theme.edge,
                shape=ft.BoxShape.CIRCLE,
                alignment=ft.Alignment.CENTER,
                on_click=lambda _: self.on_toggle_fold(node),
            )
        marker.visible = True
        marker.left = rect.x + rect.width + MARKER_GAP if side == "right" else rect.x - MARKER_GAP - MARKER_SIZE
        marker.top = rect.y + (rect.height - MARKER_SIZE) / 2
        _text(marker).value = str(descendant_count(node)) if node.folded else ""
        return marker

    @staticmethod
    def _colour(box: ft.Container, colors: Colors) -> None:
        """Sets `box`'s background and text colour from `colors`."""
        box.bgcolor = colors.background
        _text(box).color = colors.text


def _text(container: ft.Container) -> ft.Text:
    """The `Text` a box or marker was made with."""
    content = container.content
    assert isinstance(content, ft.Text)
    return content
