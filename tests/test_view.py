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


def test_reveal_leaves_a_visible_rect_alone() -> None:
    """A rect already inside the window, with the margin to spare, causes no pan at all."""
    view = View(x=0.0, y=0.0, scale=1.0)
    view.reveal(Rect(100.0, 100.0, 50.0, 20.0), 800.0, 600.0, margin=20.0)
    assert (view.x, view.y) == (0.0, 0.0)


@pytest.mark.parametrize(
    ("rect", "expected_window_position"),
    [
        (Rect(900.0, 100.0, 50.0, 20.0), (730.0, 100.0)),  # off the right: right edge at 780
        (Rect(-300.0, 100.0, 50.0, 20.0), (20.0, 100.0)),  # off the left: left edge at 20
        (Rect(100.0, 700.0, 50.0, 20.0), (100.0, 560.0)),  # off the bottom: bottom at 580
        (Rect(100.0, -50.0, 50.0, 20.0), (100.0, 20.0)),  # off the top: top at 20
    ],
)
def test_reveal_pans_only_as_far_as_needed(rect: Rect, expected_window_position: tuple[float, float]) -> None:
    """A rect off one side of the window is brought just inside the margin on that side."""
    view = View(x=0.0, y=0.0, scale=1.0)
    view.reveal(rect, 800.0, 600.0, margin=20.0)
    assert view.to_window(rect.x, rect.y) == expected_window_position


def test_reveal_keeps_the_top_left_of_a_rect_too_big_to_fit() -> None:
    """A rect wider than the window ends up with its left edge at the margin."""
    view = View(x=0.0, y=0.0, scale=2.0)
    view.reveal(Rect(1000.0, 10.0, 500.0, 20.0), 800.0, 600.0, margin=20.0)
    assert view.to_window(1000.0, 10.0)[0] == 20.0


@pytest.mark.parametrize(("x", "y", "scale"), [(0.0, 0.0, 1.0), (30.0, -10.0, 2.0), (-500.0, 120.0, 0.25)])
def test_to_content_undoes_to_window(x: float, y: float, scale: float) -> None:
    """A content point taken to the window and back is the same point, at any offset and
    scale."""
    view = View(x=x, y=y, scale=scale)
    assert view.to_content(*view.to_window(12.0, -40.0)) == pytest.approx((12.0, -40.0))
