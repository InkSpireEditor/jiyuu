"""Tests for the parts of jiyuu's window that can be checked without opening one: which
controls a map is drawn with, and in which colours."""

from typing import cast

import flet as ft
import flet.canvas as cv

from jiyuu.layout import LayoutSettings, Plane, layout
from jiyuu.measure import FixedMeasurer
from jiyuu.model import MindMap, Node
from jiyuu.theme import load_theme
from jiyuu.ui.app import MapLayer, MapWindow
from jiyuu.ui.canvas import MapDrawing

MEASURER = FixedMeasurer(width_per_char=10.0, height=16.0)
SETTINGS = LayoutSettings()
THEME = load_theme("solarized-dark")


def _tree() -> tuple[Node, Node, Node]:
    """`Project` with an unfolded `Goals` (two children) and a folded `Risks` (one child)."""
    goals = Node(text="Goals", side="right", children=[Node(text="I/O"), Node(text="TODO")])
    risks = Node(text="Risks", side="left", folded=True, children=[Node(text="Flet performance")])
    return Node(text="Project", children=[goals, risks]), goals, risks


def _draw(drawing: MapDrawing, root: Node) -> list[ft.Control]:
    """`root` laid out and drawn by `drawing`, as the window does."""
    rects, edges = layout(root, MEASURER, SETTINGS)
    plane = Plane()
    rects = plane.fit(rects, margin=40.0)
    return drawing.draw(root, rects, edges, (plane.width, plane.height))


def _drawing() -> MapDrawing:
    return MapDrawing(THEME, SETTINGS, on_select=lambda node: None, on_toggle_fold=lambda node: None)


def _controls(root: Node) -> list[ft.Control]:
    return _draw(_drawing(), root)


def _text(container: ft.Container) -> ft.Text:
    return cast(ft.Text, container.content)


def _shown(controls: list[ft.Control]) -> list[ft.Control]:
    """The controls in `controls` that are visible."""
    return [control for control in controls if control.visible is not False]


def _box(controls: list[ft.Control], text: str) -> ft.Container:
    """The box in `controls` whose text is `text`."""
    return next(c for c in controls if isinstance(c, ft.Container) and _text(c).value == text)


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
    assert _shown(rest) == rest


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


def test_a_second_draw_reuses_every_control() -> None:
    """Drawing the same map again gives back the very same controls, not new ones."""
    root, _, _ = _tree()
    drawing = _drawing()
    first = _draw(drawing, root)
    second = _draw(drawing, root)
    assert all(a is b for a, b in zip(first, second, strict=True))


def test_a_folded_branch_stays_in_the_drawing_invisible() -> None:
    """Folding hides a node's children's boxes and edges without taking them out of the
    drawing; unfolding shows the same boxes again."""
    root, goals, _ = _tree()
    drawing = _drawing()
    before = _draw(drawing, root)
    io_box = _box(before, "I/O")

    goals.folded = True
    folded = _draw(drawing, root)
    assert all(a is b for a, b in zip(folded, before, strict=True))
    assert io_box.visible is False
    canvas = cast(cv.Canvas, folded[0])
    assert sum(1 for shape in canvas.shapes if cast(cv.Path, shape).elements) == 2

    goals.folded = False
    assert io_box in _shown(_draw(drawing, root))


def test_a_node_removed_from_the_tree_loses_its_controls() -> None:
    """A node no longer in the tree is not drawn, and a new node with the same text gets a
    box of its own."""
    root, goals, _ = _tree()
    drawing = _drawing()
    old_box = _box(_draw(drawing, root), "TODO")

    goals.children[1] = Node(text="TODO")
    second = _draw(drawing, root)
    assert _box(second, "TODO") is not old_box
    assert all(control is not old_box for control in second)


class _Page:
    """Stands in for a page: records each call to `update` instead of sending anything."""

    def __init__(self) -> None:
        self.updates: list[tuple[ft.Control, ...]] = []

    def update(self, *controls: ft.Control) -> None:
        """Records `controls` as one update."""
        self.updates.append(controls)


class _Key:
    """Stands in for a key event: only its `key` is read."""

    def __init__(self, key: str) -> None:
        self.key = key


def _window(root: Node) -> tuple[MapWindow, _Page]:
    """A window over `root`, laid out, at a known size, and the page standing in for the
    screen it would send to."""
    page = _Page()
    window = MapWindow(cast(ft.Page, page), MindMap(root=root), THEME)
    window.redraw()
    window.window_size = (800.0, 600.0)
    return window, page


def _press(window: MapWindow, key: str) -> None:
    window._on_key_down(cast(ft.KeyDownEvent, _Key(key)))  # pylint: disable=protected-access


def _box_of(window: MapWindow, node: Node) -> ft.Container:
    """The drawn box for `node`: the visible box at its rect's position."""
    rect = window.rects[node]
    boxes = (cast(ft.Container, control) for control in _shown(window.layer.controls[1:]))
    return next(box for box in boxes if (box.left, box.top) == (rect.x, rect.y))


def test_window_redraw_fills_the_layer_with_the_map_at_the_view() -> None:
    """`MapWindow.redraw` lays the map out, puts its controls on the layer, sizes the
    surface and the layer to the plane it was laid out on, and places the surface where the
    view says."""
    root, _, _ = _tree()
    window, _ = _window(root)
    window.view.pan(30.0, -10.0)
    window.view.scale = 2.0
    window.redraw()

    assert window.surface.controls == [window.layer]
    assert window.surface.width == window.layer.width == window.plane.width > 0
    assert window.surface.height == window.layer.height == window.plane.height > 0
    assert len(window.layer.controls) == 8  # canvas, five boxes, two markers
    assert (window.surface.left, window.surface.top) == (30.0, -10.0)
    assert cast(ft.Scale, window.surface.scale).scale == 2.0
    assert root in window.rects


def test_the_layer_is_isolated_from_updates_to_the_surface() -> None:
    """Updating the surface does not make Flet compare every control of the map."""
    assert MapLayer().is_isolated()


def test_arrow_keys_move_the_selection_and_its_colours() -> None:
    """Right from the root selects into the right side; the new selection is drawn in the
    theme's selection colours and the old one is not any more."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    _press(window, "Arrow Right")

    assert window.selected is goals
    assert _box_of(window, goals).bgcolor == THEME.selection.background
    assert _box_of(window, root).bgcolor == THEME.root.background


def test_selecting_sends_only_the_two_recoloured_boxes_and_the_surface() -> None:
    """Selecting a node does not lay the map out or replace any control: the layer keeps
    the same list, and the update sends the two recoloured boxes and the surface."""
    root, goals, _ = _tree()
    window, page = _window(root)
    controls = window.layer.controls

    window.select(goals)

    assert window.layer.controls is controls
    assert page.updates == [(_box_of(window, root), _box_of(window, goals), window.surface)]


def test_folding_sends_the_layer_and_the_surface() -> None:
    """A fold moves boxes, so the layer is sent along with the surface."""
    root, goals, _ = _tree()
    window, page = _window(root)
    window.toggle_fold(goals)
    assert page.updates == [(window.layer, window.surface)]


def test_escape_selects_the_root_and_centres_on_it() -> None:
    """Escape, from anywhere, selects the root and puts it in the middle of the window at
    100%."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals.children[0])
    window.view.zoom_at(0.0, 0.0, 2.0)
    _press(window, "Escape")

    rect = window.rects[root]
    assert window.selected is root
    assert window.view.scale == 1.0
    assert window.view.to_window(rect.x + rect.width / 2, rect.y + rect.height / 2) == (400.0, 300.0)


def test_space_folds_and_unfolds_the_selected_node() -> None:
    """Space toggles the selected node's fold, and the selection stays on it."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, " ")
    assert goals.folded and window.selected is goals
    _press(window, " ")
    assert not goals.folded


def test_folding_over_the_selection_moves_it_to_the_folded_node() -> None:
    """Folding an ancestor of the selected node (by its marker) selects that ancestor,
    since the node that was selected is no longer shown."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals.children[1])
    window.toggle_fold(goals)
    assert window.selected is goals
    assert _box_of(window, goals).bgcolor == THEME.selection.background


def test_selecting_an_off_screen_node_pans_it_into_view() -> None:
    """A node outside the window is brought inside it when selected."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.view.pan(-5000.0, 0.0)
    window.select(goals)

    rect = window.rects[goals]
    left, _ = window.view.to_window(rect.x, rect.y)
    assert 0 <= left <= 800.0
