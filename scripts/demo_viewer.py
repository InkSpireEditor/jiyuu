"""A growing visual preview of jiyuu, run by hand to see what has been built so far.

Each step that produces something visually meaningful is meant to extend what this script
shows — folding once editing exists, an `.ink` file once that reader exists too — rather
than deferring everything visual to the dedicated viewer and editor steps. It is drawn the
way `scripts/flet_check.py` already confirmed works: one `Container` per node on a `Stack`
inside an `InteractiveViewer`, with edges as cubic Bézier curves on a `Canvas` beneath it,
in the colours of one of `jiyuu.theme`'s themes.

    poetry run python scripts/demo_viewer.py                      # a fixed example tree
    poetry run python scripts/demo_viewer.py path/to.mm           # a real Freeplane map
    poetry run python scripts/demo_viewer.py --theme nord-frost   # any bundled theme name,
                                                                  # or a path to a .yaml one
"""

from __future__ import annotations

import argparse
import sys

import flet as ft
import flet.canvas as cv

from jiyuu.formats import mm
from jiyuu.layout import Edge, LayoutSettings, Rect, layout
from jiyuu.measure import DEFAULT_FONT_PATH, DEFAULT_FONT_SIZE, PillowMeasurer
from jiyuu.model import Node
from jiyuu.theme import DEFAULT_THEME, Theme, ThemeError, available_themes, load_theme

FONT_FAMILY = "DejaVu Sans"
#: Blank space kept around the laid-out tree so no box touches the canvas's own edge.
MARGIN = 40.0


def _example_tree() -> Node:
    """The example tree used throughout jiyuu's design: `Project`, forking into `Goals`
    (right) with three children, and `Risks` (left) with one — deep enough to show the
    root and three depth levels of a theme."""
    goals = Node(
        text="Goals",
        side="right",
        children=[
            Node(text="I/O", children=[Node(text="Sockets")]),
            Node(text="TODO"),
            Node(text="TODO"),
        ],
    )
    risks = Node(text="Risks", side="left", children=[Node(text="Flet performance")])
    return Node(text="Project", children=[goals, risks])


def _tree_to_show(path: str | None) -> Node | None:
    """The tree to draw: the `.mm` file at `path`, or the example tree if `path` is `None`.
    Prints any warnings from reading a real file, and returns `None` if it could not be read
    into a tree at all — the caller's cue not to open a window."""
    if path is None:
        return _example_tree()
    with open(path, encoding="utf-8") as handle:
        mindmap, warnings = mm.read(handle.read())
    for warning in warnings:
        print(f"{path}: {warning}")
    return mindmap.root if mindmap is not None else None


def _depths(root: Node) -> dict[Node, int]:
    """Every node's distance from `root`, which picks its colours from the theme."""
    depths = {root: 0}
    pending = [root]
    while pending:
        node = pending.pop()
        for child in node.children:
            depths[child] = depths[node] + 1
            pending.append(child)
    return depths


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


def _edge_path(edge: Edge, rects: dict[Node, Rect], settings: LayoutSettings, color: str) -> cv.Path:
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
        paint=ft.Paint(color=color, style=ft.PaintingStyle.STROKE, stroke_width=2),
    )


def _build_main(root: Node, theme: Theme):
    """A Flet `main` callback that lays out and draws `root` in `theme`'s colours.

    A closure over `root` and `theme` rather than module-level globals: both are only known
    once the command line has been read and the file loaded, which happens before `ft.run`
    is ever called (see `__main__` below), so that a file that cannot be read never gets as
    far as opening a window — destroying one before it has finished mounting, tried first,
    crashes the GTK embedding this runs under.
    """

    def main(page: ft.Page) -> None:
        page.title = f"jiyuu — demo viewer — {theme.name}"
        page.fonts = {FONT_FAMILY: DEFAULT_FONT_PATH}
        page.bgcolor = theme.canvas

        measurer = PillowMeasurer(DEFAULT_FONT_PATH, DEFAULT_FONT_SIZE)
        settings = LayoutSettings()
        rects, edges = layout(root, measurer, settings)
        rects, width, height = _shift_into_view(rects)
        depths = _depths(root)

        boxes: list[ft.Control] = []
        for node, rect in rects.items():
            colors = theme.for_depth(depths[node])
            boxes.append(
                ft.Container(
                    content=ft.Text(
                        node.text, font_family=FONT_FAMILY, size=DEFAULT_FONT_SIZE, color=colors.text
                    ),
                    left=rect.x,
                    top=rect.y,
                    width=rect.width,
                    height=rect.height,
                    bgcolor=colors.background,
                    border=ft.Border.all(1, theme.edge),
                    border_radius=6,
                    alignment=ft.Alignment.CENTER,
                )
            )
        canvas = cv.Canvas(
            [_edge_path(edge, rects, settings, theme.edge) for edge in edges],
            width=width,
            height=height,
        )
        stack = ft.Stack([canvas, *boxes], width=width, height=height)
        page.add(
            ft.InteractiveViewer(
                content=stack,
                min_scale=0.25,
                max_scale=4.0,
                # The content is meant to be larger than the viewport and panned around
                # inside it. `constrained` defaults to True, which instead forces the
                # content to fit the viewport — exactly the opposite of what panning needs,
                # per this control's own documentation.
                constrained=False,
                # `boundary_margin` defaults to zero, which confines panning to exactly the
                # content's own bounds — nowhere to pan into around a small map. A generous
                # margin is what makes panning into the empty space around the map possible.
                boundary_margin=ft.Margin.all(2000),
                # Trackpad scrolling defaults to panning, not zooming, which is why
                # scrolling to zoom on a trackpad did nothing before this was set.
                trackpad_scroll_causes_scale=True,
                expand=True,
            )
        )

    return main


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Draw a mind map with jiyuu's layout.")
    parser.add_argument("path", nargs="?", help="a .mm file to draw (default: an example tree)")
    parser.add_argument(
        "--theme",
        default=DEFAULT_THEME,
        help=f"a bundled theme ({', '.join(available_themes())}) or a path to a .yaml theme",
    )
    return parser.parse_args()


if __name__ == "__main__":
    _args = _arguments()
    try:
        _theme = load_theme(_args.theme)
    except ThemeError as _error:
        print(_error, file=sys.stderr)
        sys.exit(1)
    _root = _tree_to_show(_args.path)
    if _root is None:
        sys.exit(1)
    ft.run(_build_main(_root, _theme))
