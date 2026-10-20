"""Draws a laid-out map as shapes on canvases: the edges, the node boxes, the fold markers.

Three canvases are stacked, bottom to top: one holding every edge as a cubic Bézier curve,
one holding every node's box (a filled rounded rectangle, its border, and its label centred
on it), and one holding every fold marker (a circle, and the count it shows). Every colour
comes from the `Theme` passed in. A task that is done is drawn in the theme's `task_done`
colours, its label struck through; a task in `MapDrawing.urgent` in its `urgent` colours,
with a wider border in the urgent text colour, which stays while the task is selected.

Shapes rather than one widget per node: Flutter rebuilds every widget under the drawing
surface each time the surface moves, so on a map of several hundred nodes a pan or zoom
took tens of milliseconds to draw with one widget per box. A canvas is one widget however
many shapes it holds. Clicks are matched to nodes here, by position (`node_at`,
`marker_at`), since a shape cannot receive a click of its own.

`MapDrawing` keeps the shapes it made for each node and changes them in place on every
later redraw. Flet sends a property to the window only when its value changed, but sends a
whole shape each time one is added, which on a map of several hundred nodes takes a large
part of a second; so a node hidden by a fold keeps its shapes, given no size and no text,
rather than having them taken out and added back. A rectangle or circle of size zero draws
nothing, filled or outlined, and setting a size sends two numbers where a new paint would
send every one of the paint's fields.

Each paint and text style is made once and the same object reused wherever it applies:
Flet sends a paint or text style again, in full, whenever it is replaced by another object,
even one with the same values.
"""

from __future__ import annotations

from dataclasses import dataclass

import flet as ft
import flet.canvas as cv

from ..layout import Edge, LayoutSettings, Rect, node_label
from ..measure import DEFAULT_FONT_SIZE
from ..model import Node, depths, descendant_count
from ..theme import Colors, Theme

#: The family name the bundled font is registered under on the page.
FONT_FAMILY = "DejaVu Sans"
#: A fold marker is a circle this many pixels across, just outside its node's box.
MARKER_SIZE = 18.0
#: Gap between a node's box and its fold marker.
MARKER_GAP = 2.0
MARKER_FONT_SIZE = 10
CORNER_RADIUS = 6
BORDER_WIDTH = 1
URGENT_BORDER_WIDTH = 3
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


def marker_centre(rect: Rect, side: str) -> tuple[float, float]:
    """The centre of the fold marker of a node whose box is `rect`, on its outer `side`."""
    if side == "right":
        x = rect.x + rect.width + MARKER_GAP + MARKER_SIZE / 2
    else:
        x = rect.x - MARKER_GAP - MARKER_SIZE / 2
    return (x, rect.y + rect.height / 2)


@dataclass
class _BoxShapes:
    """The shapes one node's box is drawn with."""

    fill: cv.Rect
    border: cv.Rect
    text: cv.Text


@dataclass(frozen=True)
class _Paints:
    """The paints and text style that do not depend on a node's colours: edges, a box's
    border, an urgent task's border, a fold marker's circle and its count."""

    edge: ft.Paint
    border: ft.Paint
    urgent_border: ft.Paint
    marker: ft.Paint
    count: ft.TextStyle


def _stroke(color: str, width: float) -> ft.Paint:
    """An outline `width` pixels wide, in `color`."""
    return ft.Paint(color=color, style=ft.PaintingStyle.STROKE, stroke_width=width)


@dataclass
class _MarkerShapes:
    """The shapes one node's fold marker is drawn with."""

    circle: cv.Circle
    count: cv.Text


class MapDrawing:
    """The canvases a map is drawn on, and the shapes on them, kept from one redraw to the
    next.

    A node's box, fold marker and the edge leading to it are made the first time the node
    is visible, and kept, keyed by the node, while it stays in the tree.
    """

    def __init__(self, theme: Theme, settings: LayoutSettings) -> None:
        self.theme = theme
        self.settings = settings
        # Each canvas shares its list of shapes with this drawing, which changes the list in
        # place; Flet compares a list with what it last sent, so in-place changes are sent.
        self._edge_list: list[cv.Shape] = []
        self._box_list: list[cv.Shape] = []
        self._marker_list: list[cv.Shape] = []
        self.edges = cv.Canvas(shapes=self._edge_list)
        self.boxes = cv.Canvas(shapes=self._box_list)
        self.markers = cv.Canvas(shapes=self._marker_list)
        self._box_shapes: dict[Node, _BoxShapes] = {}
        self._marker_shapes: dict[Node, _MarkerShapes] = {}
        #: Each edge's path, keyed by the edge's child: a node has one edge leading to it.
        self._paths: dict[Node, cv.Path] = {}
        self._depths: dict[Node, int] = {}
        #: The visible nodes' boxes, and the visible fold markers' centres, as last drawn.
        self._rects: dict[Node, Rect] = {}
        self._marker_centres: dict[Node, tuple[float, float]] = {}
        self._paints = _Paints(
            edge=_stroke(theme.edge, EDGE_WIDTH),
            border=_stroke(theme.edge, BORDER_WIDTH),
            urgent_border=_stroke(theme.urgent.text, URGENT_BORDER_WIDTH),
            marker=ft.Paint(color=theme.edge),
            count=ft.TextStyle(font_family=FONT_FAMILY, size=MARKER_FONT_SIZE, color=theme.canvas),
        )
        #: The task nodes drawn as urgent; set by the window, used from the next `draw`.
        self.urgent: set[Node] = set()
        #: Box fills by colour, and text styles by colour and whether they strike the text
        #: through, each made the first time it is used.
        self._fills: dict[str, ft.Paint] = {}
        self._text_styles: dict[tuple[str, bool], ft.TextStyle] = {}

    def draw(
        self,
        root: Node,
        rects: dict[Node, Rect],
        edges: list[Edge],
        size: tuple[float, float],
        selected: Node | None = None,
    ) -> list[ft.Control]:
        """The canvases, bottom to top, with every visible node's box, marker and edge drawn
        where `rects` and `edges` put them, and every other kept shape hidden.

        `rects` must already be placed on the drawing surface (see `layout.Plane`); `size` is
        that surface's width and height. The root gets no fold marker: folding it would hide
        the whole map. `selected` is drawn in the theme's selection colours.
        """
        self._depths = depths(root)
        self._forget_nodes_not_in_tree()
        self._rects = rects
        self._marker_centres = {}
        for canvas in (self.edges, self.boxes, self.markers):
            canvas.width, canvas.height = size

        for edge in edges:
            self._draw_edge(edge, rects)
        sides = {edge.child: edge.side for edge in edges}
        for node, rect in rects.items():
            self._draw_box(node, rect, node is selected)
            if node.children and node is not root:
                self._draw_marker(node, rect, sides[node])

        for node, path in self._paths.items():
            if node not in rects:
                path.elements = []
        for node, box in self._box_shapes.items():
            if node not in rects:
                for shape in (box.fill, box.border):
                    shape.width = shape.height = 0
                box.text.value = ""
        for node, marker in self._marker_shapes.items():
            if node not in self._marker_centres:
                marker.circle.radius = 0
                marker.count.value = ""
        return [self.edges, self.boxes, self.markers]

    def set_selected(self, previous: Node | None, selected: Node) -> list[cv.Shape]:
        """Recolours `previous`'s box back to its own colours (see `_colors_of`) and
        `selected`'s in the theme's selection colours, leaving every other shape as it was; returns the shapes
        recoloured."""
        changed: list[cv.Shape] = []
        if previous is not None and previous in self._rects:
            changed += self._colour(previous, self._colors_of(previous, False))
        changed += self._colour(selected, self._colors_of(selected, True))
        return changed

    def node_at(self, x: float, y: float) -> Node | None:
        """The visible node whose box contains point `(x, y)` of the drawing surface, if any."""
        for node, rect in self._rects.items():
            if rect.x <= x <= rect.x + rect.width and rect.y <= y <= rect.y + rect.height:
                return node
        return None

    def marker_at(self, x: float, y: float) -> Node | None:
        """The node whose visible fold marker contains point `(x, y)` of the drawing surface,
        if any."""
        radius = MARKER_SIZE / 2
        for node, (cx, cy) in self._marker_centres.items():
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                return node
        return None

    def _forget_nodes_not_in_tree(self) -> None:
        """Drops every kept shape of a node that is no longer in the tree."""
        stores: list[tuple[dict, list[cv.Shape]]] = [
            (self._paths, self._edge_list),
            (self._box_shapes, self._box_list),
            (self._marker_shapes, self._marker_list),
        ]
        for kept, shapes in stores:
            gone = [node for node in kept if node not in self._depths]
            if not gone:
                continue
            dropped = {id(shape) for node in gone for shape in _shapes_of(kept.pop(node))}
            shapes[:] = [shape for shape in shapes if id(shape) not in dropped]

    def _draw_edge(self, edge: Edge, rects: dict[Node, Rect]) -> None:
        """Makes `edge`'s path if new, and sets it to follow the edge's current endpoints."""
        elements = edge_elements(edge, rects, self.settings)
        path = self._paths.get(edge.child)
        if path is None:
            path = self._paths[edge.child] = cv.Path(elements, paint=self._paints.edge)
            self._edge_list.append(path)
        path.elements = elements

    def _draw_box(self, node: Node, rect: Rect, selected: bool) -> None:
        """Makes `node`'s box shapes if new, and sets them to `rect`, its label and colours."""
        box = self._box_shapes.get(node)
        if box is None:
            box = self._box_shapes[node] = _BoxShapes(
                fill=cv.Rect(0, 0, 0, 0, border_radius=CORNER_RADIUS),
                border=cv.Rect(0, 0, 0, 0, border_radius=CORNER_RADIUS, paint=self._paints.border),
                text=cv.Text(0, 0, alignment=ft.Alignment.CENTER),
            )
            self._box_list.extend(_shapes_of(box))
        for shape in (box.fill, box.border):
            shape.x, shape.y, shape.width, shape.height = rect.x, rect.y, rect.width, rect.height
        box.text.x, box.text.y = rect.x + rect.width / 2, rect.y + rect.height / 2
        box.text.value = node_label(node)
        box.border.paint = self._paints.urgent_border if self._is_urgent(node) else self._paints.border
        self._colour(node, self._colors_of(node, selected))

    def _draw_marker(self, node: Node, rect: Rect, side: str) -> None:
        """Makes `node`'s fold marker shapes if new, and places them on its outer `side`.

        Empty while the node is unfolded; while it is folded, it shows how many nodes the
        fold hides, at any depth, so a folded branch's size can be seen without opening it.
        """
        marker = self._marker_shapes.get(node)
        if marker is None:
            marker = self._marker_shapes[node] = _MarkerShapes(
                circle=cv.Circle(0, 0, 0, paint=self._paints.marker),
                count=cv.Text(0, 0, alignment=ft.Alignment.CENTER, style=self._paints.count),
            )
            self._marker_list.extend(_shapes_of(marker))
        centre = self._marker_centres[node] = marker_centre(rect, side)
        marker.circle.x, marker.circle.y = centre
        marker.circle.radius = MARKER_SIZE / 2
        marker.count.x, marker.count.y = centre
        marker.count.value = str(descendant_count(node)) if node.folded else ""

    def _colors_of(self, node: Node, selected: bool) -> Colors:
        """The colours `node`'s box is drawn in: the selection's if it is selected, else the
        theme's `task_done` if it is a task that is done, else its `urgent` if it is
        urgent (see `_is_urgent`), else its depth's."""
        if selected:
            return self.theme.selection
        if node.task is not None and node.task.done:
            return self.theme.task_done
        if self._is_urgent(node):
            return self.theme.urgent
        return self.theme.for_depth(self._depths[node])

    def _is_urgent(self, node: Node) -> bool:
        """Whether `node` is drawn as urgent: it is in `urgent`, and is a task not done. A
        task ticked done since `urgent` was set is not."""
        return node in self.urgent and node.task is not None and not node.task.done

    def _colour(self, node: Node, colors: Colors) -> list[cv.Shape]:
        """Sets `node`'s box fill and text colour from `colors`, its text struck through if
        it is a task that is done; returns the two shapes."""
        box = self._box_shapes[node]
        fill = self._fills.get(colors.background)
        if fill is None:
            fill = self._fills[colors.background] = ft.Paint(color=colors.background)
        struck = node.task is not None and node.task.done
        style = self._text_styles.get((colors.text, struck))
        if style is None:
            style = self._text_styles[(colors.text, struck)] = ft.TextStyle(
                font_family=FONT_FAMILY,
                size=DEFAULT_FONT_SIZE,
                color=colors.text,
                decoration=ft.TextDecoration.LINE_THROUGH if struck else None,
            )
        box.fill.paint, box.text.style = fill, style
        return [box.fill, box.text]



def _shapes_of(kept: cv.Path | _BoxShapes | _MarkerShapes) -> list[cv.Shape]:
    """The shapes a kept path, box or marker is drawn with, bottom to top."""
    if isinstance(kept, _BoxShapes):
        return [kept.fill, kept.border, kept.text]
    if isinstance(kept, _MarkerShapes):
        return [kept.circle, kept.count]
    return [kept]
