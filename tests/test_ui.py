"""Tests for the parts of jiyuu's window that can be checked without opening one: which
controls a map is drawn with, and in which colours."""

from typing import cast

import flet as ft
import flet.canvas as cv

from jiyuu.layout import LayoutSettings, Plane, layout
from jiyuu.measure import FixedMeasurer
from jiyuu.model import MindMap, Node, depths
from jiyuu.theme import load_theme
from jiyuu.ui.app import MapWindow
from jiyuu.ui.canvas import map_controls

MEASURER = FixedMeasurer(width_per_char=10.0, height=16.0)
SETTINGS = LayoutSettings()
THEME = load_theme("solarized-dark")


def _tree() -> tuple[Node, Node, Node]:
    """`Project` with an unfolded `Goals` (two children) and a folded `Risks` (one child)."""
    goals = Node(text="Goals", side="right", children=[Node(text="I/O"), Node(text="TODO")])
    risks = Node(text="Risks", side="left", folded=True, children=[Node(text="Flet performance")])
    return Node(text="Project", children=[goals, risks]), goals, risks


def _controls(root: Node) -> list[ft.Control]:
    rects, edges = layout(root, MEASURER, SETTINGS)
    plane = Plane()
    rects = plane.fit(rects, margin=40.0)
    return map_controls(
        root,
        rects,
        edges,
        depths=depths(root),
        theme=THEME,
        settings=SETTINGS,
        size=(plane.width, plane.height),
        on_toggle_fold=lambda node: None,
    )


def _text(container: ft.Container) -> ft.Text:
    return cast(ft.Text, container.content)


def test_map_is_one_canvas_then_a_box_per_visible_node_then_its_fold_markers() -> None:
    """A folded node's children get no box; the root and leaves get no fold marker."""
    root, _, _ = _tree()
    canvas, *rest = _controls(root)

    assert isinstance(canvas, cv.Canvas)
    # Project to Goals and to Risks, Goals to its two children; Risks's child is hidden
    assert len(canvas.shapes) == 4
    texts = [_text(cast(ft.Container, control)).value for control in rest]
    # five boxes (Project, Goals, I/O, TODO, Risks), then markers for Goals and Risks only
    assert texts[:5] == ["Project", "Goals", "I/O", "TODO", "Risks"]
    assert len(texts) == 7


def test_a_fold_marker_shows_the_hidden_count_only_while_folded() -> None:
    """Folded `Risks` shows `1`, the one node it hides; unfolded `Goals` shows nothing."""
    root, _, _ = _tree()
    *_, goals_marker, risks_marker = _controls(root)

    assert _text(cast(ft.Container, goals_marker)).value == ""
    assert _text(cast(ft.Container, risks_marker)).value == "1"


def test_every_colour_drawn_comes_from_the_theme() -> None:
    """Each box is in its depth's colours, its border and every edge in the edge colour."""
    root, _, _ = _tree()
    canvas, project, goals, *_ = _controls(root)

    assert cast(ft.Container, project).bgcolor == THEME.root.background
    assert _text(cast(ft.Container, project)).color == THEME.root.text
    assert cast(ft.Container, goals).bgcolor == THEME.for_depth(1).background
    assert all(
        cast(cv.Path, shape).paint.color == THEME.edge for shape in cast(cv.Canvas, canvas).shapes
    )


def test_window_redraw_fills_the_surface_with_the_map_at_the_view() -> None:
    """`MapWindow.redraw` lays the map out, puts its controls on the drawing surface, sizes
    the surface to the plane it was laid out on, and places it where the view says."""
    root, _, _ = _tree()
    window = MapWindow(cast(ft.Page, None), MindMap(root=root), THEME)
    window.view.pan(30.0, -10.0)
    window.view.scale = 2.0
    window.redraw()

    assert window.surface.width == window.plane.width > 0
    assert window.surface.height == window.plane.height > 0
    assert len(window.surface.controls) == 8  # canvas, five boxes, two markers
    assert (window.surface.left, window.surface.top) == (30.0, -10.0)
    assert cast(ft.Scale, window.surface.scale).scale == 2.0
    assert root in window.rects
