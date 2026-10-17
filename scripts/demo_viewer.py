"""A growing visual preview of jiyuu, run by hand to see what has been built so far.

Each step that produces something visually meaningful is meant to extend what this script
shows — a real `.mm` or `.ink` file once their readers exist, folding once editing exists —
rather than deferring everything visual to the dedicated viewer and editor steps. Today it
only draws one fixed example tree, laid out for real by `jiyuu.layout.layout`, drawn the same
way `scripts/flet_check.py` already confirmed works: one `Container` per node on a `Stack`
inside an `InteractiveViewer`, with edges as cubic Bézier curves on a `Canvas` beneath it.

    poetry run python scripts/demo_viewer.py
"""

from __future__ import annotations

import flet as ft
import flet.canvas as cv

from jiyuu.layout import Edge, LayoutSettings, Rect, layout
from jiyuu.measure import DEFAULT_FONT_PATH, DEFAULT_FONT_SIZE, PillowMeasurer
from jiyuu.model import Node

FONT_FAMILY = "DejaVu Sans"
#: Blank space kept around the laid-out tree so no box touches the canvas's own edge.
MARGIN = 40.0


def _example_tree() -> Node:
    """The example tree used throughout jiyuu's design: `Project`, forking into `Goals`
    (right) with three children, and `Risks` (left) with one."""
    goals = Node(
        text="Goals",
        side="right",
        children=[Node(text="I/O"), Node(text="TODO"), Node(text="TODO")],
    )
    risks = Node(text="Risks", side="left", children=[Node(text="Flet performance")])
    return Node(text="Project", children=[goals, risks])


def _shift_into_view(rects: dict[Node, Rect]) -> tuple[dict[Node, Rect], float, float]:
    """`rects`, translated so every box has non-negative coordinates with `MARGIN` to
    spare, plus the width and height of the plane that now holds all of them.

    `layout` centres the whole tree on `(0, 0)`, so about half of it sits at negative
    coordinates — fine for a layout in the abstract, but a `Canvas` and a `Stack` both need
    everything placed at a non-negative offset from their own top-left corner.
    """
    min_x = min(rect.x for rect in rects.values())
    min_y = min(rect.y for rect in rects.values())
    shifted = {
        node: Rect(rect.x - min_x + MARGIN, rect.y - min_y + MARGIN, rect.width, rect.height)
        for node, rect in rects.items()
    }
    width = max(rect.x + rect.width for rect in shifted.values()) + MARGIN
    height = max(rect.y + rect.height for rect in shifted.values()) + MARGIN
    return shifted, width, height


def _edge_path(edge: Edge, rects: dict[Node, Rect], settings: LayoutSettings) -> cv.Path:
    """One edge as a cubic Bézier curve from the parent's facing edge to the child's near
    edge, bulging horizontally by half of the gap `layout` left between them."""
    parent, child = rects[edge.parent], rects[edge.child]
    if edge.side == "right":
        start = (parent.x + parent.width, parent.y + parent.height / 2)
        end = (child.x, child.y + child.height / 2)
        bulge = settings.horizontal_gap / 2
    else:
        start = (parent.x, parent.y + parent.height / 2)
        end = (child.x + child.width, child.y + child.height / 2)
        bulge = -settings.horizontal_gap / 2
    control_1 = (start[0] + bulge, start[1])
    control_2 = (end[0] - bulge, end[1])
    return cv.Path(
        [
            cv.Path.MoveTo(*start),
            cv.Path.CubicTo(control_1[0], control_1[1], control_2[0], control_2[1], *end),
        ],
        paint=ft.Paint(color=ft.Colors.GREY_600, style=ft.PaintingStyle.STROKE, stroke_width=2),
    )


def main(page: ft.Page) -> None:
    """Builds the example tree, lays it out, and draws it in a pannable, zoomable view."""
    page.title = "jiyuu — demo viewer"
    page.fonts = {FONT_FAMILY: DEFAULT_FONT_PATH}

    measurer = PillowMeasurer(DEFAULT_FONT_PATH, DEFAULT_FONT_SIZE)
    settings = LayoutSettings()
    rects, edges = layout(_example_tree(), measurer, settings)
    rects, width, height = _shift_into_view(rects)

    boxes: list[ft.Control] = [
        ft.Container(
            content=ft.Text(node.text, font_family=FONT_FAMILY, size=DEFAULT_FONT_SIZE),
            left=rect.x,
            top=rect.y,
            width=rect.width,
            height=rect.height,
            bgcolor=ft.Colors.BLUE_50,
            border=ft.Border.all(1, ft.Colors.BLUE_300),
            border_radius=6,
            alignment=ft.Alignment.CENTER,
        )
        for node, rect in rects.items()
    ]
    canvas = cv.Canvas(
        [_edge_path(edge, rects, settings) for edge in edges], width=width, height=height
    )
    stack = ft.Stack([canvas, *boxes], width=width, height=height)
    page.add(
        ft.InteractiveViewer(
            content=stack,
            min_scale=0.25,
            max_scale=4.0,
            # The content is meant to be larger than the viewport and panned around inside
            # it. `constrained` defaults to True, which instead forces the content to fit
            # the viewport — exactly the opposite of what panning needs, per this control's
            # own documentation.
            constrained=False,
            # `boundary_margin` defaults to zero, which confines panning to exactly the
            # content's own bounds — nowhere to pan into around a small map. A generous
            # margin is what makes panning into the empty space around the map possible.
            boundary_margin=ft.Margin.all(2000),
            # Trackpad scrolling defaults to panning, not zooming, which is why scrolling
            # to zoom on a trackpad did nothing before this was set.
            trackpad_scroll_causes_scale=True,
            expand=True,
        )
    )


if __name__ == "__main__":
    ft.run(main)
