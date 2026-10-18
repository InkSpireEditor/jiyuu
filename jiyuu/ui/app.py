"""jiyuu's window: one map, drawn in one theme, that can be panned, zoomed and folded.

Gestures, as they reach this window from a trackpad on Linux:

- a two-finger move, or a click-and-drag, pans;
- Ctrl held during a two-finger vertical move zooms instead, around the pointer;
- Escape selects the root and puts it back in the middle of the window at 100%;
- the arrow keys move the selection (see `jiyuu.navigation`), Space folds or unfolds the
  selected node, and clicking a node selects it; the view pans just enough to keep the
  selected node in the window.

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
"""

from __future__ import annotations

from pathlib import Path

import flet as ft

from ..layout import Edge, LayoutSettings, Plane, Rect, layout
from ..measure import DEFAULT_FONT_PATH, PillowMeasurer
from ..model import MindMap, Node
from ..navigation import DOWN, HOME, LEFT, RIGHT, UP, Navigator, is_inside
from ..theme import Theme
from ..view import View
from .canvas import FONT_FAMILY, MapDrawing

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


@ft.control("Stack", isolated=True)
class MapLayer(ft.Stack):
    """The `Stack` holding every control a map is drawn with.

    Declared isolated: when a control above it is updated, Flet does not compare this
    layer's children for changes, which on a map of several hundred nodes takes around a
    tenth of a second even when none of them changed. Panning and zooming, which only move
    the drawing surface above this layer, therefore cost the same on any size of map. A
    change to this layer's children is sent only by updating the layer, or the changed
    controls, directly.
    """


class MapWindow:
    """The window's state — the map, its layout, the drawing surface, the view — and its
    controls."""

    def __init__(self, page: ft.Page, mindmap: MindMap, theme: Theme) -> None:
        self.page = page
        self.mindmap = mindmap
        self.theme = theme
        self.measurer = PillowMeasurer(DEFAULT_FONT_PATH)
        self.settings = LayoutSettings()
        self.plane = Plane()
        self.rects: dict[Node, Rect] = {}
        self.edges: list[Edge] = []
        self.view = View()
        #: The window area the map is shown in, once its size is known.
        self.window_size: tuple[float, float] | None = None
        self.ctrl_held = False
        self.navigator = Navigator(mindmap.root)
        self.selected = mindmap.root
        #: The map's controls, laid out on the drawing surface.
        self.layer = MapLayer()
        #: The map's drawing surface. Its `left`, `top` and `scale` are the view.
        self.surface = ft.Stack(controls=[self.layer])
        self.drawing = MapDrawing(theme, self.settings, on_select=self.select, on_toggle_fold=self.toggle_fold)

    def control(self) -> ft.Control:
        """The window's whole content."""
        # The Container is what fills the window: KeyboardListener is not a layout control,
        # so it cannot be made to expand itself. It also clips the map to the window.
        return ft.Container(
            expand=True,
            bgcolor=self.theme.canvas,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.KeyboardListener(
                autofocus=True,
                on_key_down=self._on_key_down,
                on_key_repeat=self._on_key_repeat,
                on_key_up=self._on_key_up,
                content=ft.GestureDetector(
                    on_scale_update=self._on_scale_update,
                    content=ft.Stack(
                        controls=[self.surface],
                        on_size_change=self._on_size_change,
                    ),
                ),
            ),
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
        node.folded = not node.folded
        if node.folded and is_inside(self.selected, node):
            self.selected = node
        self.redraw()
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
        self.page.update(*recoloured, self.surface)

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

    def _on_key_down(self, event: ft.KeyDownEvent) -> None:
        if event.key.startswith("Control"):
            self.ctrl_held = True
        elif event.key == "Escape":
            self.select(self.navigator.move(self.selected, HOME))
            self.centre_on_root()
        else:
            self._on_command_key(event.key)

    def _on_key_repeat(self, event: ft.KeyRepeatEvent) -> None:
        # Holding an arrow key keeps moving; holding Space does not keep refolding.
        if event.key in NAVIGATION_KEYS:
            self._on_command_key(event.key)

    def _on_command_key(self, key: str) -> None:
        if key in NAVIGATION_KEYS:
            target = self.navigator.move(self.selected, NAVIGATION_KEYS[key])
            if target is not self.selected:
                self.select(target)
        elif key == " ":
            self.toggle_fold(self.selected)

    def _on_key_up(self, event: ft.KeyUpEvent) -> None:
        if event.key.startswith("Control"):
            self.ctrl_held = False


def run(mindmap: MindMap, path: Path, theme: Theme) -> None:
    """Opens a window showing `mindmap`, read from `path`, in `theme`; returns when it closes."""

    def main(page: ft.Page) -> None:
        page.title = f"{path.name} — jiyuu"
        page.fonts = {FONT_FAMILY: DEFAULT_FONT_PATH}
        page.bgcolor = theme.canvas
        page.padding = 0
        window = MapWindow(page, mindmap, theme)
        window.redraw()
        page.add(window.control())

    ft.run(main)
