"""Tests for the parts of jiyuu's window that can be checked without opening one: which
shapes a map is drawn with, in which colours, and what a click or a key does."""

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import cast

import flet as ft
import flet.canvas as cv
import pytest

from jiyuu.document import Document, open_document
from jiyuu.layout import LayoutSettings, Plane, layout
from jiyuu.measure import FixedMeasurer
from jiyuu.model import MindMap, Node
from jiyuu.theme import load_theme
from jiyuu.ui.app import MIN_FIELD_WIDTH, MapLayer, MapWindow, TextEdit, typed_character
from jiyuu.ui.canvas import MapDrawing, marker_centre

MEASURER = FixedMeasurer(width_per_char=10.0, height=16.0)
SETTINGS = LayoutSettings()
THEME = load_theme("solarized-dark")


def _tree() -> tuple[Node, Node, Node]:
    """`Project` with an unfolded `Goals` (two children) and a folded `Risks` (one child)."""
    goals = Node(text="Goals", side="right", children=[Node(text="I/O"), Node(text="TODO")])
    risks = Node(text="Risks", side="left", folded=True, children=[Node(text="Flet performance")])
    return Node(text="Project", children=[goals, risks]), goals, risks


def _draw(drawing: MapDrawing, root: Node, selected: Node | None = None) -> None:
    """`root` laid out and drawn by `drawing`, as the window does."""
    rects, edges = layout(root, MEASURER, SETTINGS)
    plane = Plane()
    drawing.draw(root, plane.fit(rects, margin=40.0), edges, (plane.width, plane.height), selected)


def _drawn(root: Node) -> MapDrawing:
    """A drawing of `root`."""
    drawing = MapDrawing(THEME, SETTINGS)
    _draw(drawing, root)
    return drawing


def _boxes(drawing: MapDrawing) -> list[tuple[cv.Rect, cv.Rect, cv.Text]]:
    """Each box drawn, as its fill, border and text, in the order they were made."""
    shapes = drawing.boxes.shapes
    return [
        (cast(cv.Rect, shapes[i]), cast(cv.Rect, shapes[i + 1]), cast(cv.Text, shapes[i + 2]))
        for i in range(0, len(shapes), 3)
    ]


def _box(drawing: MapDrawing, text: str) -> tuple[cv.Rect, cv.Rect, cv.Text]:
    """The box drawn with `text`."""
    return next(box for box in _boxes(drawing) if box[2].value == text)


def _markers(drawing: MapDrawing) -> list[tuple[cv.Circle, cv.Text]]:
    """Each fold marker drawn, as its circle and its count, in the order they were made."""
    shapes = drawing.markers.shapes
    return [(cast(cv.Circle, shapes[i]), cast(cv.Text, shapes[i + 1])) for i in range(0, len(shapes), 2)]


def _paths_drawn(drawing: MapDrawing) -> int:
    """How many edges are drawn: the paths that have elements."""
    return sum(1 for shape in drawing.edges.shapes if cast(cv.Path, shape).elements)


def test_map_is_drawn_as_edges_then_boxes_then_fold_markers() -> None:
    """A folded node's children get no box; the root and leaves get no fold marker."""
    root, _, _ = _tree()
    drawing = _drawn(root)

    # Project to Goals and to Risks, Goals to its two children; Risks's child is hidden
    assert len(drawing.edges.shapes) == _paths_drawn(drawing) == 4
    assert [text.value for _, _, text in _boxes(drawing)] == ["Project", "Goals", "I/O", "TODO", "Risks"]
    assert len(_markers(drawing)) == 2  # Goals and Risks


def test_a_fold_marker_shows_the_hidden_count_only_while_folded() -> None:
    """Folded `Risks` shows `1`, the one node it hides; unfolded `Goals` shows nothing."""
    root, _, _ = _tree()
    (_, goals_count), (_, risks_count) = _markers(_drawn(root))

    assert goals_count.value == ""
    assert risks_count.value == "1"


def test_every_colour_drawn_comes_from_the_theme() -> None:
    """Each box is in its depth's colours, its border and every edge in the edge colour,
    and each fold marker in the edge colour with its count in the canvas colour."""
    root, _, _ = _tree()
    drawing = _drawn(root)
    project_fill, _, project_text = _box(drawing, "Project")
    goals_fill, _, _ = _box(drawing, "Goals")

    assert project_fill.paint.color == THEME.root.background
    assert cast(ft.TextStyle, project_text.style).color == THEME.root.text
    assert goals_fill.paint.color == THEME.for_depth(1).background
    assert all(border.paint.color == THEME.edge for _, border, _ in _boxes(drawing))
    assert all(cast(cv.Path, shape).paint.color == THEME.edge for shape in drawing.edges.shapes)
    for circle, count in _markers(drawing):
        assert circle.paint.color == THEME.edge
        assert cast(ft.TextStyle, count.style).color == THEME.canvas


def test_a_second_draw_keeps_every_shape() -> None:
    """Drawing the same map again changes the same shapes, rather than making new ones."""
    root, _, _ = _tree()
    drawing = _drawn(root)
    before = [list(canvas.shapes) for canvas in (drawing.edges, drawing.boxes, drawing.markers)]
    _draw(drawing, root)
    after = [canvas.shapes for canvas in (drawing.edges, drawing.boxes, drawing.markers)]
    assert all(a is b for old, new in zip(before, after, strict=True) for a, b in zip(old, new, strict=True))


def test_redrawing_and_reselecting_keep_the_same_paint_objects() -> None:
    """A redraw, or selecting a node and then the one before it again, leaves every shape
    with the very paint and text style objects it had: a different object with the same
    values would be sent to the window again."""
    root, goals, _ = _tree()
    drawing = MapDrawing(THEME, SETTINGS)
    _draw(drawing, root, selected=root)
    styles = [(box[0].paint, box[1].paint, box[2].style) for box in _boxes(drawing)]

    _draw(drawing, root, selected=root)
    drawing.set_selected(root, goals)
    drawing.set_selected(goals, root)
    after = [(box[0].paint, box[1].paint, box[2].style) for box in _boxes(drawing)]
    assert all(a is b for old, new in zip(styles, after, strict=True) for a, b in zip(old, new, strict=True))


def test_a_folded_branch_keeps_its_shapes_hidden() -> None:
    """Folding hides a node's children's boxes and edges, by giving them no size, text
    or elements, without taking their shapes out; unfolding draws the same shapes again."""
    root, goals, _ = _tree()
    drawing = _drawn(root)
    fill, border, text = _box(drawing, "I/O")
    shapes = list(drawing.boxes.shapes)

    goals.folded = True
    _draw(drawing, root)
    assert all(a is b for a, b in zip(drawing.boxes.shapes, shapes, strict=True))
    assert (fill.width, fill.height, border.width, border.height, text.value) == (0, 0, 0, 0, "")
    assert _paths_drawn(drawing) == 2

    goals.folded = False
    _draw(drawing, root)
    assert all(a is b for a, b in zip(_box(drawing, "I/O"), (fill, border, text)))
    assert fill.width > 0 and text.value == "I/O"
    assert _paths_drawn(drawing) == 4


def test_a_node_removed_from_the_tree_loses_its_shapes() -> None:
    """A node no longer in the tree has its shapes taken out, and a new node with the same
    text gets shapes of its own."""
    root, goals, _ = _tree()
    drawing = _drawn(root)
    old = _box(drawing, "TODO")

    goals.children[1] = Node(text="TODO")
    _draw(drawing, root)
    assert len(_boxes(drawing)) == 5
    assert all(shape is not kept for shape in old for kept in drawing.boxes.shapes)


def test_node_at_and_marker_at_find_what_a_point_is_on() -> None:
    """A point inside a box finds its node, a point on a fold marker finds the marker's
    node, and a point on nothing, or on a hidden node, finds nothing."""
    root, goals, _ = _tree()
    rects, edges = layout(root, MEASURER, SETTINGS)
    rects = Plane().fit(rects, margin=40.0)
    drawing = MapDrawing(THEME, SETTINGS)
    drawing.draw(root, rects, edges, (2000.0, 2000.0))
    rect, io_rect = rects[goals], rects[goals.children[0]]

    assert drawing.node_at(rect.x + 1, rect.y + rect.height / 2) is goals
    assert drawing.marker_at(*marker_centre(rect, "right")) is goals
    assert drawing.node_at(0.0, 0.0) is None and drawing.marker_at(0.0, 0.0) is None

    goals.folded = True
    rects, edges = layout(root, MEASURER, SETTINGS)
    drawing.draw(root, Plane().fit(rects, margin=40.0), edges, (2000.0, 2000.0))
    assert drawing.node_at(io_rect.x + 1, io_rect.y + 1) is None


class _Task:
    """Stands in for a task started by `run_task`: records whether it was cancelled, and
    whether a test has run it."""

    def __init__(self, handler: object) -> None:
        self.handler = handler
        self.cancelled = False
        self.ran = False

    def cancel(self) -> bool:
        """Records the task as cancelled."""
        self.cancelled = True
        return True


class _Page:
    """Stands in for a page: records each call to `update`, `run_task`, `show_dialog` and
    `pop_dialog` instead of sending or running anything."""

    def __init__(self) -> None:
        self.updates: list[tuple[ft.Control, ...]] = []
        self.tasks: list[_Task] = []
        self.dialogs: list[ft.DialogControl] = []
        self.title = ""

    def update(self, *controls: ft.Control) -> None:
        """Records `controls` as one update."""
        self.updates.append(controls)

    def run_task(self, handler: object) -> _Task:
        """Records `handler` as one task to run, without running it."""
        task = _Task(handler)
        self.tasks.append(task)
        return task

    def show_dialog(self, dialog: ft.DialogControl) -> None:
        """Records `dialog` as shown."""
        self.dialogs.append(dialog)

    def pop_dialog(self) -> None:
        """Records the latest dialog shown as closed."""
        self.dialogs.pop()

    def handlers(self) -> list[object]:
        """What each task recorded was started with."""
        return [task.handler for task in self.tasks]


class _FieldEvent:
    """Stands in for an event from a text field: only its `control` is read."""

    def __init__(self, control: ft.TextField | None) -> None:
        self.control = control


class _Key:
    """Stands in for a key event: only its `key` is read."""

    def __init__(self, key: str) -> None:
        self.key = key


def _window(root: Node, path: Path = Path("map.ink")) -> tuple[MapWindow, _Page]:
    """A window over `root`, saved to `path`, laid out, at a known size, and the page
    standing in for the screen it would send to. The page runs no task, so no save is ever
    made unless a test runs one itself."""
    page = _Page()
    doc = Document(source=path, path=path, mindmap=MindMap(root=root), last_io_hash=b"")
    window = MapWindow(cast(ft.Page, page), doc, THEME)
    window.control()
    window.redraw()
    window.window_size = (800.0, 600.0)
    return window, page


def _press(window: MapWindow, key: str) -> None:
    window._on_key_down(cast(ft.KeyDownEvent, _Key(key)))  # pylint: disable=protected-access


def _press_with(window: MapWindow, modifiers: list[str], key: str) -> None:
    """Presses `key` while holding `modifiers` (such as `"Control Left"`), then lets them go."""
    for modifier in modifiers:
        _press(window, modifier)
    _press(window, key)
    for modifier in modifiers:
        window._on_key_up(cast(ft.KeyUpEvent, _Key(modifier)))  # pylint: disable=protected-access


def _editing(window: MapWindow) -> TextEdit:
    """The window's open text field."""
    assert window.text_edit is not None
    return window.text_edit


def _submit(window: MapWindow, text: str) -> None:
    """Types `text` into the open text field, replacing what it held, and presses Enter."""
    field = _editing(window).field
    field.value = text
    window._on_field_done(cast(ft.Event[ft.TextField], _FieldEvent(field)))  # pylint: disable=protected-access


def _fill_of(window: MapWindow, node: Node) -> cv.Rect:
    return _box(window.drawing, node.text)[0]


def _colour_of(window: MapWindow, node: Node) -> str | None:
    return _fill_of(window, node).paint.color


def _click(window: MapWindow, point: tuple[float, float]) -> None:
    """A click on content point `point`, at the window position the view shows it at."""
    window.tap_at(*window.view.to_window(*point))


def test_window_redraw_fills_the_layer_with_the_map_at_the_view() -> None:
    """`MapWindow.redraw` lays the map out, puts the canvases on the layer, sizes the
    surface, the layer and the canvases to the plane it was laid out on, and places the
    surface where the view says."""
    root, _, _ = _tree()
    window, _ = _window(root)
    window.view.pan(30.0, -10.0)
    window.view.scale = 2.0
    window.redraw()

    drawing = window.drawing
    assert window.surface.controls == [window.layer]
    assert window.layer.controls == [drawing.edges, drawing.boxes, drawing.markers]
    assert window.surface.width == window.layer.width == drawing.boxes.width == window.plane.width > 0
    assert window.surface.height == window.layer.height == drawing.boxes.height == window.plane.height > 0
    assert (window.surface.left, window.surface.top) == (30.0, -10.0)
    assert cast(ft.Scale, window.surface.scale).scale == 2.0
    assert root in window.rects


def test_the_layer_is_isolated_from_updates_to_the_surface() -> None:
    """Updating the surface does not make Flet compare every shape of the map."""
    assert MapLayer().is_isolated()


def test_arrow_keys_move_the_selection_and_its_colours() -> None:
    """Right from the root selects into the right side; the new selection is drawn in the
    theme's selection colours and the old one is not any more."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    _press(window, "Arrow Right")

    assert window.selected is goals
    assert _colour_of(window, goals) == THEME.selection.background
    assert _colour_of(window, root) == THEME.root.background


def test_selecting_sends_only_the_two_recoloured_boxes_and_the_surface() -> None:
    """Selecting a node does not lay the map out: the update sends the fill and text of the
    two recoloured boxes, and the surface."""
    root, goals, _ = _tree()
    window, page = _window(root)

    window.select(goals)

    root_fill, _, root_text = _box(window.drawing, "Project")
    goals_fill, _, goals_text = _box(window.drawing, "Goals")
    assert page.updates == [(root_fill, root_text, goals_fill, goals_text, window.surface)]


def test_folding_sends_the_layer_and_the_surface() -> None:
    """A fold moves boxes, so the layer is sent along with the surface."""
    root, goals, _ = _tree()
    window, page = _window(root)
    window.toggle_fold(goals)
    assert page.updates == [(window.layer, window.surface)]


def test_clicking_a_box_selects_its_node() -> None:
    """A click inside a node's box selects that node."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.view.pan(25.0, 40.0)
    window.view.scale = 1.5
    rect = window.rects[goals.children[1]]
    _click(window, (rect.x + 2, rect.y + 2))
    assert window.selected is goals.children[1]


def test_clicking_a_fold_marker_folds_or_unfolds_its_node() -> None:
    """A click on a node's fold marker folds it, and a second click unfolds it."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    centre = marker_centre(window.rects[goals], "right")
    _click(window, centre)
    assert goals.folded
    _click(window, centre)
    assert not goals.folded


def test_clicking_empty_space_does_nothing() -> None:
    """A click on no box and no marker leaves the selection and every fold as they were."""
    root, _, _ = _tree()
    window, page = _window(root)
    _click(window, (1.0, 1.0))
    assert window.selected is root
    assert page.updates == []


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
    assert _colour_of(window, goals) == THEME.selection.background


def test_selecting_an_off_screen_node_pans_it_into_view() -> None:
    """A node outside the window is brought inside it when selected."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.view.pan(-5000.0, 0.0)
    window.select(goals)

    rect = window.rects[goals]
    left, _ = window.view.to_window(rect.x, rect.y)
    assert 0 <= left <= 800.0


def test_insert_tab_and_enter_add_a_node_and_select_it() -> None:
    """Insert and Tab add a child of the selected node, Enter a sibling; each new node is
    selected and drawn, and the layer and surface are sent."""
    root, goals, _ = _tree()
    window, page = _window(root)
    window.select(goals)
    page.updates.clear()

    _press(window, "Insert")
    child = goals.children[-1]
    assert window.selected is child and child.text == ""
    assert child in window.rects
    assert page.updates == [(window.layer, window.surface), (window.surface,)]
    assert _editing(window).node is child
    _press(window, "Escape")

    _press(window, "Enter")
    assert goals.children[-1] is window.selected is not child
    assert _editing(window).node is window.selected
    _press(window, "Escape")

    _press(window, "Tab")
    assert window.selected.text == "" and window.selected in goals.children[-1].children


def test_delete_removes_the_selected_node_and_selects_a_neighbour() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    io, todo = goals.children
    window.select(todo)
    _press(window, "Delete")
    assert goals.children == [io]
    assert window.selected is io
    assert _colour_of(window, io) == THEME.selection.background


def test_a_key_that_changes_nothing_sends_nothing() -> None:
    """Delete on the root and Ctrl+Up on a first sibling change nothing, so nothing is
    laid out or sent."""
    root, goals, _ = _tree()
    window, page = _window(root)
    _press(window, "Delete")
    window.select(goals.children[0])
    page.updates.clear()
    _press_with(window, ["Control Left"], "Arrow Up")
    assert page.updates == []
    assert window.selected is goals.children[0]


def test_ctrl_up_and_down_move_the_selected_node() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    io, todo = goals.children
    window.select(todo)
    _press_with(window, ["Control Left"], "Arrow Up")
    assert goals.children == [todo, io]
    assert window.selected is todo
    _press_with(window, ["Control Left"], "Arrow Down")
    assert goals.children == [io, todo]


def test_ctrl_and_the_arrow_towards_the_root_promotes_or_changes_side() -> None:
    """On the right side, Ctrl+Left moves a node next to its parent; on a first-level node
    it moves the node to the left side. Ctrl+Right, away from the root, does nothing."""
    root, goals, risks = _tree()
    window, _ = _window(root)
    todo = goals.children[1]
    window.select(todo)
    _press_with(window, ["Control Left"], "Arrow Right")
    assert todo in goals.children

    _press_with(window, ["Control Left"], "Arrow Left")
    assert root.children == [goals, todo, risks] and todo.side == "right"
    _press_with(window, ["Control Left"], "Arrow Left")
    assert todo.side == "left"
    assert window.selected is todo
    assert window.rects[todo].x < window.rects[root].x


def test_holding_ctrl_and_an_arrow_keeps_moving_the_node() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    io, todo = goals.children
    window.select(todo)
    _press(window, "Control Left")
    window._on_key_repeat(cast(ft.KeyRepeatEvent, _Key("Arrow Up")))  # pylint: disable=protected-access
    assert goals.children == [todo, io]


def test_ctrl_z_undoes_and_ctrl_y_and_ctrl_shift_z_redo() -> None:
    """Undo puts the deleted node back and selects it again; both redo keys delete it again."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    io, todo = goals.children
    window.select(todo)
    _press(window, "Delete")

    _press_with(window, ["Control Left"], "Z")
    assert goals.children == [io, todo] and window.selected is todo
    assert todo in window.rects
    _press_with(window, ["Control Left"], "Y")
    assert goals.children == [io] and window.selected is io

    _press_with(window, ["Control Left"], "Z")
    _press_with(window, ["Control Left", "Shift Left"], "Z")
    assert goals.children == [io]
    assert not window.shift_held and not window.ctrl_held


def test_a_fold_can_be_undone() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, " ")
    _press_with(window, ["Control Left"], "Z")
    assert not goals.folded and window.selected is goals


def test_undo_with_nothing_to_undo_sends_nothing() -> None:
    root, _, _ = _tree()
    window, page = _window(root)
    _press_with(window, ["Control Left"], "Z")
    _press_with(window, ["Control Left"], "Y")
    assert page.updates == []


@pytest.mark.parametrize(
    ("key", "shift", "character"),
    [
        ("A", False, "a"),
        ("A", True, "A"),
        ("É", False, "é"),
        ("1", False, "1"),
        ("-", True, "-"),
        (" ", False, None),
        ("F2", False, None),
        ("Arrow Up", False, None),
    ],
)
def test_typed_character(key: str, shift: bool, character: str | None) -> None:
    assert typed_character(key, shift) == character


def test_f2_opens_a_field_over_the_node_holding_its_text_selected() -> None:
    root, goals, _ = _tree()
    window, page = _window(root)
    window.select(goals)
    page.updates.clear()
    _press(window, "F2")

    text_edit = _editing(window)
    field, box = text_edit.field, text_edit.box
    assert text_edit.node is goals
    assert window.surface.controls == [window.layer, box] and box.content is field
    assert field.value == "Goals"
    assert field.selection == ft.TextSelection(0, 5)
    rect = window.rects[goals]
    assert (box.left, box.top, box.height) == (rect.x, rect.y, rect.height)
    assert box.width == max(rect.width, MIN_FIELD_WIDTH)
    assert page.updates == [(window.surface,)]
    assert page.handlers()[-1] == field.focus


def test_typing_a_character_opens_the_field_holding_only_that_character() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press_with(window, ["Shift Left"], "Q")
    field = _editing(window).field
    assert field.value == "Q"
    assert field.selection == ft.TextSelection(1, 1)


def test_enter_in_the_field_renames_the_node_and_lays_the_map_out_again() -> None:
    """The node gets the field's text, without surrounding spaces; its box widens to fit;
    the field closes; and the keyboard is handed back to the window."""
    root, goals, _ = _tree()
    window, page = _window(root)
    window.select(goals)
    _press(window, "F2")
    field = _editing(window).field
    width = window.rects[goals].width
    page.updates.clear()

    _submit(window, "  Goals and more  ")

    assert goals.text == "Goals and more"
    assert window.rects[goals].width > width
    assert window.text_edit is None
    assert window.surface.controls == [window.layer]
    assert page.updates == [(window.layer, window.surface)]
    assert field.focus in page.handlers()
    assert cast(ft.KeyboardListener, window.keyboard).focus in page.handlers()
    assert "Goals and more" in [text.value for _, _, text in _boxes(window.drawing)]


def test_escape_closes_the_field_and_keeps_the_text() -> None:
    root, goals, _ = _tree()
    window, page = _window(root)
    window.select(goals)
    _press(window, "F2")
    _editing(window).field.value = "Foo"
    page.updates.clear()
    _press(window, "Escape")

    assert goals.text == "Goals"
    assert window.text_edit is None and window.surface.controls == [window.layer]
    assert page.updates == [(window.surface,)]
    assert window.editor.undo_stack == []


def test_keys_do_nothing_else_while_the_field_is_open() -> None:
    """Arrows, Space, Delete, Insert, F2, letters and Ctrl+Z are left to the field."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "F2")
    text_edit = _editing(window)
    for key in ("Arrow Right", " ", "Delete", "Insert", "Enter", "F2", "A"):
        _press(window, key)
    window._on_key_repeat(cast(ft.KeyRepeatEvent, _Key("Arrow Up")))  # pylint: disable=protected-access
    _press_with(window, ["Control Left"], "Z")

    assert window.selected is goals and window.text_edit is text_edit
    assert not goals.folded and [child.text for child in goals.children] == ["I/O", "TODO"]


def test_a_short_node_gets_a_field_wide_enough_to_type_in() -> None:
    """A new, empty node's field is `MIN_FIELD_WIDTH` wide, starting at the box's left edge."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "Insert")
    box = _editing(window).box
    rect = window.rects[window.selected]
    assert rect.width < MIN_FIELD_WIDTH
    assert (box.left, box.width) == (rect.x, MIN_FIELD_WIDTH)


def test_the_field_widens_leftwards_on_the_left_side() -> None:
    """On the left side, the field keeps its right edge on the box's right edge."""
    root, _, risks = _tree()
    window, _ = _window(root)
    window.select(risks)
    _press(window, "Insert")
    box = _editing(window).box
    rect = window.rects[window.selected]
    assert cast(float, box.left) + cast(float, box.width) == rect.x + rect.width


def test_a_field_already_closed_is_ignored() -> None:
    """A late event from a field that was closed changes nothing."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "F2")
    old = _editing(window).field
    _press(window, "Escape")
    _press(window, "F2")
    current = window.text_edit

    window._on_field_done(cast(ft.Event[ft.TextField], _FieldEvent(old)))  # pylint: disable=protected-access
    assert window.text_edit is current and goals.text == "Goals"


def test_clicking_while_the_field_is_open_keeps_its_text_then_clicks() -> None:
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "F2")
    _editing(window).field.value = "Plans"
    rect = window.rects[root]
    _click(window, (rect.x + 2, rect.y + 2))

    assert goals.text == "Plans"
    assert window.text_edit is None and window.selected is root


def test_a_new_node_named_then_undone_loses_its_name_then_itself() -> None:
    """Naming a new node is its own change: the first Ctrl+Z empties its text, the second
    removes it."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "Insert")
    child = window.selected
    _submit(window, "Foo")
    assert child.text == "Foo"

    _press_with(window, ["Control Left"], "Z")
    assert child.text == "" and child in goals.children
    _press_with(window, ["Control Left"], "Z")
    assert child not in goals.children and window.selected is goals


def test_the_field_is_drawn_unlike_any_node() -> None:
    """The field is hollow: the canvas colour inside a border, text and cursor in the edge
    colour."""
    root, goals, _ = _tree()
    window, _ = _window(root)
    window.select(goals)
    _press(window, "F2")
    field, box = _editing(window).field, _editing(window).box

    assert box.bgcolor == THEME.canvas
    assert cast(ft.Border, box.border).top.color == THEME.edge
    assert cast(ft.TextStyle, field.text_style).color == field.cursor_color == THEME.edge


async def _no_wait(_seconds: float) -> None:
    """Stands in for `asyncio.sleep`, returning at once."""


def _run_saves(page: _Page, monkeypatch: pytest.MonkeyPatch) -> None:
    """Runs every save the page was asked to schedule, and that was neither cancelled nor
    run already, without waiting for its delay."""
    monkeypatch.setattr("jiyuu.ui.saving.asyncio.sleep", _no_wait)
    for task in list(page.tasks):
        if not task.cancelled and not task.ran and getattr(task.handler, "__name__", "") == "later":
            task.ran = True
            asyncio.run(cast(Callable[[], Coroutine[None, None, None]], task.handler)())


def _ink_window(tmp_path: Path) -> tuple[MapWindow, _Page, Path]:
    """A window over the map in a new `.ink` file in `tmp_path`, and that file."""
    path = tmp_path / "map.ink"
    path.write_text("- Project\n  - Goals\n  - Risks\n", encoding="utf-8")
    doc, _ = open_document(path)
    assert doc is not None
    page = _Page()
    window = MapWindow(cast(ft.Page, page), doc, THEME)
    window.control()
    window.redraw()
    window.window_size = (800.0, 600.0)
    return window, page, path


def _click_button(dialog: ft.DialogControl, label: str) -> None:
    """Clicks the button labelled `label` in a banner's or dialog's actions."""
    for button in cast(ft.Banner, dialog).actions:
        button = cast(ft.TextButton, button)
        if cast(ft.Text, button.content).value == label:
            cast(Callable[[object], None], button.on_click)(None)
            return
    raise LookupError(label)


def test_a_change_is_saved_once_after_the_last_of_several(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each change cancels the save the one before it scheduled; running the one left saves
    the map."""
    window, page, path = _ink_window(tmp_path)
    _press(window, "Arrow Right")
    _press(window, "Insert")
    _submit(window, "Foo")

    saves = [task for task in page.tasks if getattr(task.handler, "__name__", "") == "later"]
    assert [task.cancelled for task in saves] == [True, False]
    _run_saves(page, monkeypatch)
    assert "    - Foo\n" in path.read_text(encoding="utf-8")


def test_a_file_changed_on_disk_shows_a_banner_and_reload_shows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, page, path = _ink_window(tmp_path)
    path.write_text("- Edited elsewhere\n  - Foo\n", encoding="utf-8")
    _press(window, "Delete")  # the root: nothing changes, nothing is scheduled
    _press(window, "Arrow Right")
    _press(window, " ")
    _press(window, "Insert")
    _run_saves(page, monkeypatch)

    (banner,) = page.dialogs
    assert isinstance(banner, ft.Banner)
    assert "changed outside jiyuu" in cast(ft.Text, banner.content).value
    assert "Edited elsewhere" in path.read_text(encoding="utf-8")

    _click_button(banner, "Reload")
    assert page.dialogs == []
    assert window.mindmap.root.text == "Edited elsewhere"
    assert window.selected is window.mindmap.root
    assert "Edited elsewhere" in [text.value for _, _, text in _boxes(window.drawing)]


def test_keep_mine_writes_the_window_s_map_over_the_changed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, page, path = _ink_window(tmp_path)
    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    _press(window, "F2")
    _submit(window, "Plans")
    _run_saves(page, monkeypatch)

    _click_button(page.dialogs[0], "Keep mine")
    assert page.dialogs == []
    assert "- Plans\n" in path.read_text(encoding="utf-8")


def test_a_map_with_no_file_asks_for_a_name_at_its_first_change(tmp_path: Path) -> None:
    """The dialog suggests the first free name; a name already taken is refused; a free
    one is saved to, and becomes the window's title."""
    source = tmp_path / "worked-example.mm"
    source.write_text('<map><node TEXT="Project"><node TEXT="Goals"/></node></map>', encoding="utf-8")
    (tmp_path / "worked-example.ink").write_text("- Earlier\n", encoding="utf-8")
    doc, _ = open_document(source)
    assert doc is not None and doc.path is None
    page = _Page()
    window = MapWindow(cast(ft.Page, page), doc, THEME)
    window.control()
    window.redraw()
    _press(window, "Insert")

    (dialog,) = page.dialogs
    field = cast(ft.TextField, window.saving.name_field)
    assert isinstance(dialog, ft.AlertDialog)
    assert field.value == "worked-example-2.ink"

    field.value = "worked-example"
    _click_button(dialog, "Save")
    assert field.error == "worked-example.ink already exists"
    assert page.dialogs == [dialog]

    field.value = "plans"
    _click_button(dialog, "Save")
    assert page.dialogs == []
    assert doc.path == tmp_path / "plans.ink" and doc.path.exists()
    assert page.title == "plans.ink — jiyuu"
    assert (tmp_path / "worked-example.ink").read_text(encoding="utf-8") == "- Earlier\n"


def test_a_save_that_fails_shows_a_banner_offering_to_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    window, page, path = _ink_window(tmp_path)
    _press(window, " ")  # the root cannot fold: nothing to save
    _press(window, "Arrow Right")
    _press(window, "Insert")

    def failing(_path: Path, _text: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("jiyuu.document.write_text_atomically", failing)
    _run_saves(page, monkeypatch)
    (banner,) = page.dialogs
    assert "disk full" in cast(ft.Text, cast(ft.Banner, banner).content).value

    monkeypatch.undo()
    _click_button(banner, "Retry")
    assert page.dialogs == []
    _run_saves(page, monkeypatch)
    assert path.read_text(encoding="utf-8").count("  - ") == 3


def test_a_file_changed_on_disk_shows_the_banner_without_a_change_in_the_window(tmp_path: Path) -> None:
    """The check made every second finds the change; nothing was edited in the window. A
    second check while the banner is shown shows nothing more."""
    window, page, path = _ink_window(tmp_path)
    window.saving.check_disk()
    assert page.dialogs == []

    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    window.saving.check_disk()
    window.saving.check_disk()
    (banner,) = page.dialogs
    assert isinstance(banner, ft.Banner)
    assert window.saving.doc.conflicted

    _click_button(banner, "Reload")
    assert window.mindmap.root.text == "Edited elsewhere"


def test_the_check_drops_a_save_waiting_to_happen(tmp_path: Path) -> None:
    window, page, path = _ink_window(tmp_path)
    _press(window, "Arrow Right")
    _press(window, "Insert")
    path.write_text("- Edited elsewhere\n", encoding="utf-8")
    window.saving.check_disk()
    saves = [task for task in page.tasks if getattr(task.handler, "__name__", "") == "later"]
    assert all(task.cancelled for task in saves)
