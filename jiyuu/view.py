"""Where a map is shown in a window: an offset and a scale, and how gestures change them.

A content point `(px, py)` — a position on the map's own drawing surface — appears in the
window at `(x + scale * px, y + scale * py)`. Panning moves `(x, y)`; zooming changes
`scale`, and moves `(x, y)` with it so that the point being zoomed around stays where it is
in the window. Nothing here draws anything: the window applies a `View` to the map's
drawing surface.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Rect

#: The smallest and largest scale a view can be zoomed to.
MIN_SCALE = 0.25
MAX_SCALE = 4.0


@dataclass
class View:
    """The window's offset `(x, y)` and `scale` for showing a map's drawing surface."""

    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0

    def to_window(self, px: float, py: float) -> tuple[float, float]:
        """Where content point `(px, py)` appears in the window."""
        return (self.x + self.scale * px, self.y + self.scale * py)

    def pan(self, dx: float, dy: float) -> None:
        """Moves everything shown by `(dx, dy)` window pixels."""
        self.x += dx
        self.y += dy

    def zoom_at(self, wx: float, wy: float, factor: float) -> None:
        """Multiplies the scale by `factor`, kept within `MIN_SCALE`..`MAX_SCALE`, while the
        content point at window position `(wx, wy)` stays at `(wx, wy)`."""
        scale = min(MAX_SCALE, max(MIN_SCALE, self.scale * factor))
        ratio = scale / self.scale
        self.x = wx - (wx - self.x) * ratio
        self.y = wy - (wy - self.y) * ratio
        self.scale = scale

    def centre_on(self, rect: Rect, window_width: float, window_height: float) -> None:
        """Back to a scale of 1, with the centre of `rect` (in content coordinates) in the
        middle of a window of the given size."""
        self.scale = 1.0
        self.x = window_width / 2 - (rect.x + rect.width / 2)
        self.y = window_height / 2 - (rect.y + rect.height / 2)
