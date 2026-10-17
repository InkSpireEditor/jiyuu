"""Tests for the view: where a map is shown in a window, and how gestures change it."""

import pytest

from jiyuu.layout import Rect
from jiyuu.view import MAX_SCALE, MIN_SCALE, View


def test_pan_moves_every_point_by_the_same_window_distance() -> None:
    """Panning by `(dx, dy)` moves any content point by exactly `(dx, dy)` in the window,
    whatever the scale."""
    view = View(x=10.0, y=20.0, scale=2.0)
    before = view.to_window(100.0, 50.0)
    view.pan(15.0, -5.0)
    assert view.to_window(100.0, 50.0) == (before[0] + 15.0, before[1] - 5.0)


@pytest.mark.parametrize("factor", [0.5, 1.1, 2.0])
def test_zoom_keeps_the_point_under_the_pointer_still(factor: float) -> None:
    """Whatever the factor, the content point at the zoom's window position stays there."""
    view = View(x=-150.0, y=40.0, scale=1.0)
    pointer = (300.0, 120.0)
    content_point = ((pointer[0] - view.x) / view.scale, (pointer[1] - view.y) / view.scale)

    view.zoom_at(*pointer, factor)

    assert view.scale == pytest.approx(factor)
    assert view.to_window(*content_point) == pytest.approx(pointer)


def test_zoom_stops_at_the_limits_and_still_keeps_the_pointer_still() -> None:
    """Asking for more than the maximum zooms only up to it, and the point under the
    pointer still does not move; zooming out past the minimum likewise."""
    view = View(scale=MAX_SCALE / 2)
    view.zoom_at(200.0, 100.0, 10.0)
    assert view.scale == MAX_SCALE
    assert view.to_window(200.0 / (MAX_SCALE / 2), 100.0 / (MAX_SCALE / 2)) == pytest.approx((200.0, 100.0))

    view.zoom_at(200.0, 100.0, 1e-6)
    assert view.scale == MIN_SCALE


def test_centre_on_puts_the_rect_in_the_middle_at_full_scale() -> None:
    """After `centre_on`, the scale is 1 and the rect's centre is the window's centre."""
    view = View(x=500.0, y=-300.0, scale=3.0)
    view.centre_on(Rect(100.0, 40.0, 80.0, 30.0), 800.0, 600.0)

    assert view.scale == 1.0
    assert view.to_window(140.0, 55.0) == (400.0, 300.0)
