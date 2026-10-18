"""jiyuu's window: one map, drawn in one theme, that can be panned, zoomed, folded and
edited.

Gestures, as they reach this window from a trackpad on Linux:

- a two-finger move, or a click-and-drag, pans;
- Ctrl held during a two-finger vertical move zooms instead, around the pointer;
- Escape selects the root and puts it back in the middle of the window at 100%;
- the arrow keys move the selection (see `jiyuu.navigation`), Space folds or unfolds the
  selected node, and clicking a node selects it; the view pans just enough to keep the
  selected node in the window;
- clicking the circle beside a node folds or unfolds its branch.

Keys that change the map, each acting on the selected node (see `jiyuu.editing`):

- F2 opens a text field over the node, holding its text, all selected so that typing
  replaces it; typing a character opens the field holding just that character. Enter
  keeps the text typed, as does clicking anywhere outside the field; Escape closes the
  field and leaves the node's text as it was. While the field is open, every other key
  is typed into it, or edits the text in it, and does nothing else;
- Insert or Tab adds an empty child, Enter an empty sibling, and opens the text field on
  the new node;
- Delete deletes the node and its branch;
- Ctrl+Up and Ctrl+Down move the node up or down among its siblings;
- Ctrl and the arrow pointing towards the root moves the node up one level, next to its
  parent; on a node directly under the root, it moves the node to the root's other side;
- Ctrl+Z undoes the latest change, folds included; Ctrl+Y and Ctrl+Shift+Z redo it.

Every change, folds included, is saved to the map's file shortly after it is made (see
`jiyuu.ui.saving`).

Nodes are drawn as shapes on canvases (see `jiyuu.ui.canvas`), which cannot receive a click
of their own; a click is matched to a node by where it lands on the map.

Panning, zooming and Escape change a `View` (an offset and a scale, see `jiyuu.view`),
which is then applied to the map's drawing surface as its `left`, `top` and `scale` in a
single update. Flet's `InteractiveViewer` was used for this first; it was replaced because
it can only zoom around its content's top-left corner, so zooming around the pointer took a
zoom call and then a pan call, and the frame drawn between the two made zooming visibly
jitter.

A trackpad pinch is not offered: on the Linux desktop this runs on, it reaches Flet as a
two-finger move whose scale stays at 1, so it cannot be told apart from a pan. Ctrl is
tracked with a `KeyboardListener` because it reports key releases as well as key presses;
the page-wide keyboard event reports only presses, and so cannot tell when Ctrl is let go.
Shift is tracked the same way, since a `KeyboardListener` event carries only the key.

A `KeyboardListener` event names the key pressed, not the character it types. The
character that opens the text field is worked out from the key's name and Shift (see
`typed_character`), which gives the right character for a letter, but can give another
character than the one printed on the key for a key that types a different character with
Shift held. Every character after the first is typed into the field itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import flet as ft

from ..document import Document
from ..editing import Editor
from ..layout import Edge, LayoutSettings, Plane, Rect, layout
from ..measure import DEFAULT_FONT_PATH, DEFAULT_FONT_SIZE, PillowMeasurer
from ..model import MindMap, Node
from ..navigation import DOWN, HOME, LEFT, RIGHT, UP, Navigator, is_inside
from ..theme import Theme
from ..view import View
from .canvas import CORNER_RADIUS, FONT_FAMILY, MapDrawing
from .saving import Saving, window_title

#: How much a Ctrl + two-finger vertical move zooms: each pixel moved multiplies the scale
#: by `1 + ZOOM_PER_PIXEL * pixels`. The sign was chosen by hand on a trackpad with natural
#: scrolling turned on, where the opposite sign zoomed the wrong way; with natural scrolling
#: off, the same gesture reports the opposite sign, and so zooms the opposite way.
ZOOM_PER_PIXEL = 0.01
#: Blank space kept around the map on its drawing surface.
MARGIN = 40.0
#: How close to the window's edge the selected node may get before the view pans to keep
#: it in, in window pixels.
REVEAL_MARGIN = 24.0
#: Keys, as Flet names them, that move the selection, and the move each one makes.
NAVIGATION_KEYS = {
    "Arrow Right": RIGHT,
    "Arrow Left": LEFT,
    "Arrow Up": UP,
    "Arrow Down": DOWN,
}
#: Keys that add a node, and the `Editor` method each one calls.
ADD_KEYS = {
    "Insert": Editor.add_child,
    "Tab": Editor.add_child,
    "Enter": Editor.add_sibling,
}
#: The narrowest the text field opened over a node is, in pixels of the drawing surface, so
#: that a node with short or no text still has room to type in.
MIN_FIELD_WIDTH = 120.0
#: The width of the border around the text field, wider than a node's own border.
FIELD_BORDER_WIDTH = 2


def typed_character(key: str, shift: bool) -> str | None:
    """The character typed by pressing the key Flet names `key`, with Shift held if
    `shift`, or `None` if the key does not type a character on its own.

    A letter key is named by its capital letter, and types it in lower case unless Shift is
    held. Any other key named by a single character is taken to type that character. The
    space bar is not counted: it folds the selected node.
    """
    if len(key) != 1 or key == " ":
        return None
    if key.isalpha() and not shift:
        return key.lower()
    return key


@ft.control("Stack", isolated=True)
class MapLayer(ft.Stack):
    """The `Stack` holding the canvases a map is drawn on.

    Declared isolated: when a control above it is updated, Flet does not compare this
    layer's children for changes, which on a map of several hundred nodes, with several
    shapes per node, takes tens of milliseconds even when none of them changed. Panning and zooming, which only move
    the drawing surface above this layer, therefore cost the same on any size of map. A
    change to this layer's children is sent only by updating the layer, or the changed
    controls, directly.
    """


@dataclass
class TextEdit:
    """A node whose text is being edited: the node, the field its text is edited in, and
    the container drawing the box around the field."""

    node: Node
    field: ft.TextField
    box: ft.Container


class MapWindow:
    """The window's state — the map, its layout, the drawing surface, the view — and its
    controls."""

    def __init__(self, page: ft.Page, doc: Document, theme: Theme) -> None:
        self.page = page
        mindmap = self.mindmap = doc.mindmap
        self.theme = theme
        self.measurer = PillowMeasurer(DEFAULT_FONT_PATH)
        self.settings = LayoutSettings()
        self.plane = Plane()
        self.rects: dict[Node, Rect] = {}
        self.edges: list[Edge] = []
        self.view = View()
        #: The window area the map is shown in, once its size is known.
        self.window_size: tuple[float, float] | None = None
        #: The modifier keys held down: `"Control"` and `"Shift"`, whichever side of the
        #: keyboard they are on.
        self.held: set[str] = set()
        self.editor = Editor(mindmap.root)
        #: The node whose text is being edited, if any, and the field it is edited in.
        self.text_edit: TextEdit | None = None
        #: The control the window's key presses reach while no text is being edited.
        self.keyboard: ft.KeyboardListener | None = None
        self.navigator = Navigator(mindmap.root)
        self.selected = mindmap.root
        #: The map's controls, laid out on the drawing surface.
        self.layer = MapLayer()
        #: The map's drawing surface. Its `left`, `top` and `scale` are the view.
        self.surface = ft.Stack(controls=[self.layer])
        self.drawing = MapDrawing(theme, self.settings)
        self.saving = Saving(page, doc, theme, self.show_map, self.take_keyboard)

    def control(self) -> ft.Control:
        """The window's whole content."""
        # The Container is what fills the window: KeyboardListener is not a layout control,
        # so it cannot be made to expand itself. It also clips the map to the window.
        self.keyboard = ft.KeyboardListener(
            autofocus=True,
            on_key_down=self._on_key_down,
            on_key_repeat=self._on_key_repeat,
            on_key_up=self._on_key_up,
            content=ft.GestureDetector(
                on_scale_update=self._on_scale_update,
                on_tap_up=self._on_tap_up,
                content=ft.Stack(
                    controls=[self.surface],
                    on_size_change=self._on_size_change,
                ),
            ),
        )
        return ft.Container(
            expand=True,
            bgcolor=self.theme.canvas,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=self.keyboard,
        )

    def redraw(self) -> None:
        """Lays the map out again and moves every control drawing it to its new place."""
        root = self.mindmap.root
        rects, self.edges = layout(root, self.measurer, self.settings)
        self.rects = self.plane.fit(rects, MARGIN)
        size = (self.plane.width, self.plane.height)
        self.surface.width, self.surface.height = size
        self.layer.width, self.layer.height = size
        self.layer.controls = self.drawing.draw(root, self.rects, self.edges, size, self.selected)
        self.apply_view()

    def apply_view(self) -> None:
        """Sets the drawing surface's position and scale from `view`, without sending them."""
        self.surface.left, self.surface.top = self.view.x, self.view.y
        self.surface.scale = ft.Scale(scale=self.view.scale, alignment=ft.Alignment.TOP_LEFT)

    def toggle_fold(self, node: Node) -> None:
        """Folds `node` if it is unfolded, unfolds it otherwise, and redraws the map.

        A node with no children, or the root, is left alone. Folding a node the selection
        is inside moves the selection up to that node, since the selected one is no longer
        shown.
        """
        if not node.children or node is self.mindmap.root:
            return
        self.editor.toggle_fold(node)
        selected = node if node.folded and is_inside(self.selected, node) else self.selected
        # The view stays where it is: a fold is often made by clicking a marker far from
        # the selected node, which should not pan back to it.
        self.show_change(selected, reveal=False)

    def start_editing(self, node: Node, text: str | None = None) -> None:
        """Opens a text field over `node`'s box and gives it the keyboard.

        The field is drawn hollow, in the canvas colour with a thicker border, its text and
        cursor in the edge colour, so that it looks unlike any node's box, selected or not.

        Without `text`, the field holds `node`'s text, all of it selected; with `text`, it
        holds `text` with the cursor after it. The field is on the drawing surface, so it
        moves and zooms with the map. It covers the node's box, and is at least
        `MIN_FIELD_WIDTH` wide, growing away from the root on the left side of the map.

        The field keeps its size while text is typed into it, and scrolls its text once
        the text is wider than it; the node's box is resized to the new text when the
        field closes. Changing the field's size while text is typed into it sends the field
        to the window again, and that moved the cursor back to where the field had placed
        it when it opened.
        """
        rect = self.rects[node]
        value = node.text if text is None else text
        field = ft.TextField(
            value=value,
            selection=ft.TextSelection(0 if text is None else len(value), len(value)),
            autofocus=True,
            dense=True,
            border=ft.NoInputBorder(),
            content_padding=ft.Padding.symmetric(horizontal=self.settings.pad_x),
            text_align=ft.TextAlign.CENTER,
            text_style=ft.TextStyle(font_family=FONT_FAMILY, size=DEFAULT_FONT_SIZE, color=self.theme.edge),
            cursor_color=self.theme.edge,
            on_submit=self._on_field_done,
            on_blur=self._on_field_done,
        )
        # The box around the field is drawn by a container exactly as tall as the node's
        # box, which centres the field's line in it as the canvas centres a node's text:
        # a text field on its own is as tall as the font's line, not as the node's box.
        box = ft.Container(
            content=field,
            top=rect.y,
            height=rect.height,
            alignment=ft.Alignment.CENTER,
            bgcolor=self.theme.canvas,
            border=ft.Border.all(FIELD_BORDER_WIDTH, self.theme.edge),
            border_radius=CORNER_RADIUS,
        )
        width = max(rect.width, MIN_FIELD_WIDTH)
        box.width = width
        box.left = rect.x + rect.width - width if self.navigator.side_of(node) == LEFT else rect.x
        self.text_edit = TextEdit(node, field, box)
        self.surface.controls = [self.layer, box]
        self.page.update(self.surface)
        # The field is asked for the keyboard once it is on screen: `autofocus` alone does
        # not give it the keyboard when the field is added to a page already shown.
        self.page.run_task(self._focus_field, field)

    async def _focus_field(self, field: ft.TextField) -> None:
        """Gives `field` the keyboard, unless it was closed in the meantime: a closed field
        is no longer on the page, and Flet raises when asked to focus it."""
        if self.text_edit is not None and self.text_edit.field is field:
            await field.focus()

    def finish_editing(self, keep: bool) -> None:
        """Closes the text field, if one is open, and gives the keyboard back to the window.
        If `keep`, the node's text becomes the text in the field (see `Editor.rename`), and
        the map is laid out again around it."""
        text_edit = self.text_edit
        if text_edit is None:
            return
        self.text_edit = None
        self.surface.controls = [self.layer]
        version = self.editor.version
        if keep:
            self.editor.rename(text_edit.node, text_edit.field.value or "")
        if self.editor.version != version:
            self.show_change(text_edit.node)
        else:
            self.page.update(self.surface)
        self.take_keyboard()

    def take_keyboard(self) -> None:
        """Gives the keyboard back to the window, for its own keys to work again."""
        if self.keyboard is not None:
            self.page.run_task(self.keyboard.focus)

    def show_map(self, mindmap: MindMap) -> None:
        """Shows `mindmap` instead of the map shown so far, with the root selected. The undo
        history of the map shown so far is dropped."""
        if self.text_edit is not None:
            self.text_edit = None
            self.surface.controls = [self.layer]
        self.mindmap = mindmap
        self.editor = Editor(mindmap.root)
        self.navigator = Navigator(mindmap.root)
        self.selected = mindmap.root
        self.redraw()
        self.page.update(self.layer, self.surface)

    def _on_field_done(self, event: ft.Event[ft.TextField]) -> None:
        # Called when Enter submits the field and when the field loses the keyboard. One
        # Enter can do both, and a closed field can still report losing the keyboard; only
        # a call for the field that is still open does anything.
        if self.text_edit is not None and event.control is self.text_edit.field:
            self.finish_editing(keep=True)

    def edit(self, command: Callable[[Editor, Node], Node]) -> None:
        """Runs `command`, an `Editor` method, on the selected node, and shows the result
        with the node it returns selected. A command that changed nothing sends nothing."""
        version = self.editor.version
        selected = command(self.editor, self.selected)
        if self.editor.version != version:
            self.show_change(selected)

    def undo(self) -> None:
        """Undoes the latest change, and selects the node that was selected before it."""
        selected = self.editor.undo()
        if selected is not None:
            self.show_change(selected)

    def redo(self) -> None:
        """Makes the latest undone change again, and selects the node it selected."""
        selected = self.editor.redo()
        if selected is not None:
            self.show_change(selected)

    def show_change(self, selected: Node, reveal: bool = True) -> None:
        """Lays out and redraws the map after a change to its tree, with `selected` selected
        and, if `reveal`, panned into the window; sends the drawing and the surface."""
        self.selected = selected
        self.saving.changed()
        self.redraw()
        if reveal and self.window_size is not None:
            self.view.reveal(self.rects[selected], *self.window_size, REVEAL_MARGIN)
            self.apply_view()
        self.page.update(self.layer, self.surface)

    def select(self, node: Node) -> None:
        """Selects `node`, recolours it and the node selected before, and pans just enough
        to keep it in the window. Nothing moves, so the map is not laid out again, and only
        the two recoloured boxes and the surface's position are sent."""
        recoloured = self.drawing.set_selected(self.selected, node)
        self.selected = node
        if self.window_size is not None:
            self.view.reveal(self.rects[node], *self.window_size, REVEAL_MARGIN)
            self.apply_view()
        # `Page.update` is annotated as taking `Control`s, but sends any Flet control,
        # canvas shapes included.
        self.page.update(*cast(list[ft.Control], recoloured), self.surface)

    def centre_on_root(self) -> None:
        """Back to 100%, with the root's box in the middle of the window."""
        if self.window_size is None:
            return
        self.view.centre_on(self.rects[self.mindmap.root], *self.window_size)
        self.apply_view()
        self.page.update(self.surface)

    def _on_size_change(self, event: ft.LayoutSizeChangeEvent) -> None:
        first = self.window_size is None
        self.window_size = (event.width, event.height)
        if first:
            self.centre_on_root()

    def _on_scale_update(self, event: ft.ScaleUpdateEvent) -> None:
        if self.ctrl_held:
            if event.pointer_count != 2 or not event.focal_point_delta.y:
                return
            self.view.zoom_at(
                event.local_focal_point.x,
                event.local_focal_point.y,
                1 + event.focal_point_delta.y * ZOOM_PER_PIXEL,
            )
        else:
            self.view.pan(event.focal_point_delta.x, event.focal_point_delta.y)
        self.apply_view()
        self.page.update(self.surface)

    def _on_tap_up(self, event: ft.TapEvent) -> None:
        if event.local_position is None:
            return
        self.tap_at(event.local_position.x, event.local_position.y)

    def tap_at(self, wx: float, wy: float) -> None:
        """Handles a click at window position `(wx, wy)`: folds or unfolds the node whose
        fold marker is there, or else selects the node whose box is there, or else does
        nothing. A text field still open is closed first, keeping its text."""
        self.finish_editing(keep=True)
        x, y = self.view.to_content(wx, wy)
        marked = self.drawing.marker_at(x, y)
        if marked is not None:
            self.toggle_fold(marked)
            return
        node = self.drawing.node_at(x, y)
        if node is not None:
            self.select(node)

    @property
    def ctrl_held(self) -> bool:
        """Whether Ctrl is held down."""
        return "Control" in self.held

    @property
    def shift_held(self) -> bool:
        """Whether Shift is held down."""
        return "Shift" in self.held

    def _on_key_down(self, event: ft.KeyDownEvent) -> None:
        modifier = _modifier(event.key)
        if modifier is not None:
            self.held.add(modifier)
        elif self.text_edit is not None:
            # Every other key is the text field's own while it is open.
            if event.key == "Escape":
                self.finish_editing(keep=False)
        elif event.key == "Escape":
            self.select(self.navigator.move(self.selected, HOME))
            self.centre_on_root()
        else:
            self._on_command_key(event.key)

    def _on_key_repeat(self, event: ft.KeyRepeatEvent) -> None:
        # Holding an arrow key keeps moving the selection, or the node with Ctrl held;
        # holding any other key does not repeat its command.
        if event.key in NAVIGATION_KEYS and self.text_edit is None:
            self._on_command_key(event.key)

    def _on_command_key(self, key: str) -> None:
        if self.ctrl_held:
            self._on_ctrl_key(key)
        elif key in NAVIGATION_KEYS:
            target = self.navigator.move(self.selected, NAVIGATION_KEYS[key])
            if target is not self.selected:
                self.select(target)
        elif key == " ":
            self.toggle_fold(self.selected)
        elif key in ADD_KEYS:
            self.edit(ADD_KEYS[key])
            self.start_editing(self.selected)
        elif key == "Delete":
            self.edit(Editor.delete)
        elif key == "F2":
            self.start_editing(self.selected)
        elif (character := typed_character(key, self.shift_held)) is not None:
            self.start_editing(self.selected, character)

    def _on_ctrl_key(self, key: str) -> None:
        """Handles `key` pressed with Ctrl held."""
        if key == "Arrow Up":
            self.edit(Editor.move_up)
        elif key == "Arrow Down":
            self.edit(Editor.move_down)
        elif key in ("Arrow Left", "Arrow Right") and self.selected is not self.mindmap.root:
            side = self.navigator.side_of(self.selected)
            towards_root = LEFT if side == RIGHT else RIGHT
            if NAVIGATION_KEYS[key] != towards_root:
                return
            if self.selected in self.mindmap.root.children:
                self.edit(lambda editor, node: editor.set_side(node, towards_root))
            else:
                self.edit(Editor.promote)
        elif key == "Z":
            if self.shift_held:
                self.redo()
            else:
                self.undo()
        elif key == "Y":
            self.redo()

    def _on_key_up(self, event: ft.KeyUpEvent) -> None:
        self.held.discard(_modifier(event.key) or "")


def _modifier(key: str) -> str | None:
    """`"Control"` or `"Shift"` if `key`, as Flet names it, is one of those keys, on either
    side of the keyboard (`"Control Left"`, `"Shift Right"`, ...); otherwise `None`."""
    for modifier in ("Control", "Shift"):
        if key.startswith(modifier):
            return modifier
    return None


def run(doc: Document, theme: Theme) -> None:
    """Opens a window showing `doc`'s map in `theme`; returns when it closes."""

    def main(page: ft.Page) -> None:
        page.title = window_title(doc)
        page.fonts = {FONT_FAMILY: DEFAULT_FONT_PATH}
        page.bgcolor = theme.canvas
        page.padding = 0
        window = MapWindow(page, doc, theme)
        window.redraw()
        page.add(window.control())

    ft.run(main)
