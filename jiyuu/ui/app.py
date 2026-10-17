"""jiyuu's window: one map, drawn in one theme, that can be panned, zoomed and folded.

Gestures, as they reach this window from a trackpad on Linux:

- a two-finger move, or a click-and-drag, pans;
- Ctrl held during a two-finger vertical move zooms instead, around the pointer;
- Escape puts the root back in the middle of the window at 100%.

All three change a `View` (an offset and a scale, see `jiyuu.view`), which is then applied
to the map's drawing surface as its `left`, `top` and `scale` in a single update. Flet's
`InteractiveViewer` was used for this first; it was replaced because it can only zoom around
its content's top-left corner, so zooming around the pointer took a zoom call and then a
pan call, and the frame drawn between the two made zooming visibly jitter.

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
from ..model import MindMap, Node, depths
from ..theme import Theme
from ..view import View
from .canvas import FONT_FAMILY, map_controls

#: How much a Ctrl + two-finger vertical move zooms: each pixel moved multiplies the scale
#: by `1 + ZOOM_PER_PIXEL * pixels`. The sign was chosen by hand on a trackpad with natural
#: scrolling turned on, where the opposite sign zoomed the wrong way; with natural scrolling
#: off, the same gesture reports the opposite sign, and so zooms the opposite way.
ZOOM_PER_PIXEL = 0.01
#: Blank space kept around the map on its drawing surface.
MARGIN = 40.0


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
        #: The map's drawing surface. Its `left`, `top` and `scale` are the view.
        self.surface = ft.Stack()

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
        """Lays the map out again and rebuilds every control drawing it."""
        root = self.mindmap.root
        rects, self.edges = layout(root, self.measurer, self.settings)
        self.rects = self.plane.fit(rects, MARGIN)
        self.surface.width, self.surface.height = self.plane.width, self.plane.height
        self.surface.controls = map_controls(
            root,
            self.rects,
            self.edges,
            depths=depths(root),
            theme=self.theme,
            settings=self.settings,
            size=(self.plane.width, self.plane.height),
            on_toggle_fold=self.toggle_fold,
        )
        self.apply_view()

    def apply_view(self) -> None:
        """Sets the drawing surface's position and scale from `view`, without sending them."""
        self.surface.left, self.surface.top = self.view.x, self.view.y
        self.surface.scale = ft.Scale(scale=self.view.scale, alignment=ft.Alignment.TOP_LEFT)

    def toggle_fold(self, node: Node) -> None:
        """Folds `node` if it is unfolded, unfolds it otherwise, and redraws the map."""
        node.folded = not node.folded
        self.redraw()
        self.surface.update()

    def centre_on_root(self) -> None:
        """Back to 100%, with the root's box in the middle of the window."""
        if self.window_size is None:
            return
        self.view.centre_on(self.rects[self.mindmap.root], *self.window_size)
        self.apply_view()
        self.surface.update()

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
        self.surface.update()

    def _on_key_down(self, event: ft.KeyDownEvent) -> None:
        if event.key.startswith("Control"):
            self.ctrl_held = True
        elif event.key == "Escape":
            self.centre_on_root()

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
