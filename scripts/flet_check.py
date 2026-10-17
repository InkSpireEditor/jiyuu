"""Checks whether Flet 1.0 can support jiyuu's planned rendering approach.

jiyuu's viewer draws a mind map as one `Container` per node, absolutely positioned on a
`Stack`, inside an `InteractiveViewer` for panning and zooming, with edges drawn underneath
on a `Canvas`; it predicts how much space a node's text needs with Pillow before asking Flet
to render it, and it drives most editing through keyboard shortcuts. This script exercises
each of those assumptions on their own, against a real Flet window, rather than leaving them
untested until the viewer and the editor are built on top of them:

    poetry run python scripts/flet_check.py auto       # window + layout + text measurement;
                                                         # closes itself, no interaction needed
    poetry run python scripts/flet_check.py keyboard    # keyboard events; stays open and
                                                         # needs real key presses — close the
                                                         # window when done, or it times out
    poetry run python scripts/flet_check.py gestures    # pointer gestures; same, but needs a
                                                         # trackpad or mouse used by hand
    poetry run python scripts/flet_check.py transform   # pan/zoom without InteractiveViewer;
                                                         # same, used by hand

`auto` prints one line of results per check to standard output. `keyboard` prints one line
per key event as it is pressed, each noting whether a `TextField` on the same page had focus
at the time.
"""

from __future__ import annotations

import asyncio
import sys
import time

import flet as ft
from PIL import ImageFont

#: A font whose licence (Bitstream Vera, permissive, redistribution-with-notice) permits
#: bundling it with jiyuu; this script reads it from the system installation this check was
#: run against rather than bundling a copy, since bundling the asset itself is a later step.
FONT_PATH = "/usr/share/fonts/TTF/DejaVuSans.ttf"
FONT_FAMILY = "DejaVu Sans"
FONT_SIZE = 16

#: Matches the node count jiyuu's maps are expected to stay under.
NODE_COUNT = 200

#: Node-length strings covering plain ASCII, a non-ASCII letter, and the punctuation marks a
#: node's text is otherwise allowed to contain freely (`/`, `#`, `"`).
SAMPLE_STRINGS = [
    "Project", "Goals", "I/O", "TODO", "Risks", "Flet performance",
    "Résumé", "A/B", "#tag", 'He said "hi"',
]

#: How long `keyboard` waits for the window to be closed by hand before giving up.
KEYBOARD_CHECK_TIMEOUT = 120


async def _check_b(page: ft.Page) -> None:
    """Time `page.update()` while panning and zooming 200 positioned containers.

    Mirrors the shape of jiyuu's planned canvas: `NODE_COUNT` containers on a `Stack`
    inside an `InteractiveViewer`. Panning and zooming are driven through
    `InteractiveViewer.pan`/`.zoom` rather than a real pointer gesture, since what is being
    measured is Flet's own update latency, not gesture recognition.
    """
    containers: list[ft.Control] = [
        ft.Container(
            content=ft.Text(f"Node {i}", font_family=FONT_FAMILY),
            left=(i % 20) * 90,
            top=(i // 20) * 40,
            bgcolor=ft.Colors.BLUE_100,
            padding=8,
        )
        for i in range(NODE_COUNT)
    ]
    stack = ft.Stack(controls=containers, width=20 * 90, height=10 * 40)
    # constrained=False: the default, True, forces content bigger than the viewport to fit
    # the viewport instead, which breaks real pointer-driven panning and zooming entirely
    # (found only later, by hand, once something used this for real — the timing measured
    # below is unaffected either way, since InteractiveViewer.pan/.zoom bypass gesture
    # recognition and manipulate the transform directly).
    viewer = ft.InteractiveViewer(content=stack, constrained=False)
    page.add(viewer)
    page.update()
    await asyncio.sleep(0.3)  # let the first paint settle before timing updates

    update_times_ms = []
    for _ in range(5):
        started = time.perf_counter()
        await viewer.zoom(1.2)
        page.update()
        update_times_ms.append((time.perf_counter() - started) * 1000)
    for _ in range(5):
        started = time.perf_counter()
        await viewer.pan(30, 10)
        page.update()
        update_times_ms.append((time.perf_counter() - started) * 1000)

    page.controls.remove(viewer)
    print(
        "B: update time per pan/zoom call, in ms (10 calls): "
        + ", ".join(f"{t:.1f}" for t in update_times_ms)
    )


async def _check_c(page: ft.Page) -> None:
    """Compare Pillow's predicted text width against Flet's own rendered width.

    Each sample string is drawn in an otherwise unstyled `Container`, whose
    `on_size_change` reports the size Flet actually laid it out at. Pillow's prediction for
    the same string and font is `ImageFont.getlength`, exactly what jiyuu's layout would use
    to reserve space for a node before Flet has rendered anything.
    """
    rendered: dict[str, tuple[float, float]] = {}

    def on_size_change(label: str):
        def handler(event: ft.LayoutSizeChangeEvent) -> None:
            rendered[label] = (event.width, event.height)

        return handler

    column = ft.Column(
        controls=[
            ft.Container(
                content=ft.Text(text, font_family=FONT_FAMILY, size=FONT_SIZE),
                on_size_change=on_size_change(text),
            )
            for text in SAMPLE_STRINGS
        ]
    )
    page.add(column)
    page.update()
    await asyncio.sleep(0.6)  # on_size_change fires after layout, not immediately

    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    largest_diff = 0.0
    for text in SAMPLE_STRINGS:
        predicted = font.getlength(text)
        actual = rendered.get(text)
        diff = (actual[0] - predicted) if actual else None
        if diff is not None:
            largest_diff = max(largest_diff, abs(diff))
        print(
            f"C: {text!r}: pillow={predicted:.2f} flet={actual} "
            + (f"diff={diff:+.2f}" if diff is not None else "diff=MISSING")
        )
    print(f"C: largest absolute difference across all samples: {largest_diff:.2f}px")

    page.controls.remove(column)


async def run_auto(page: ft.Page) -> None:
    """Run checks A, B and C in sequence, then close the window on its own."""
    page.title = "jiyuu — flet_check"
    page.fonts = {FONT_FAMILY: FONT_PATH}
    print("A: window opened and mounted without error")

    await _check_b(page)
    await _check_c(page)

    await asyncio.sleep(0.2)
    await page.window.destroy()


async def run_keyboard(page: ft.Page) -> None:
    """Run check D: log every key event, and whether a `TextField` had focus when it fired.

    Stays open for `KEYBOARD_CHECK_TIMEOUT` seconds or until the window is closed by hand,
    whichever comes first, since this check needs a person to actually press the keys.
    """
    page.title = "jiyuu — flet_check (keyboard)"
    focus = {"value": False}

    def on_focus(_) -> None:
        focus["value"] = True

    def on_blur(_) -> None:
        focus["value"] = False

    def on_keyboard_event(event: ft.KeyboardEvent) -> None:
        mods = "".join(
            name for name, held in
            (("shift", event.shift), ("ctrl", event.ctrl), ("alt", event.alt), ("meta", event.meta))
            if held
        )
        print(
            f"D: key={event.key!r} mods={mods or '-'} "
            f"text_field_focused={focus['value']}",
            flush=True,
        )

    closed = {"value": False}

    def on_disconnect(_) -> None:
        closed["value"] = True

    page.on_keyboard_event = on_keyboard_event
    page.on_disconnect = on_disconnect
    page.add(
        ft.Text(
            "Press each of: every arrow key, Tab, Insert, Enter, F2, Delete, Space, "
            "Ctrl+Z, Ctrl+Y. Click the field below to give it focus, then press them again. "
            "Close this window when done."
        ),
        ft.TextField(label="Focus me, then press the keys above again", on_focus=on_focus, on_blur=on_blur),
    )
    page.update()

    waited = 0.0
    while not closed["value"] and waited < KEYBOARD_CHECK_TIMEOUT:
        await asyncio.sleep(0.5)
        waited += 0.5
    print("D: check ended (window closed or timed out)")


async def run_gestures(page: ft.Page) -> None:
    """Log which events a trackpad's or mouse's gestures actually produce over a map.

    The map is a grid of containers inside an `InteractiveViewer` configured to pan on a
    trackpad's two-finger scroll (`trackpad_scroll_causes_scale=False`), itself inside a
    `GestureDetector` whose `on_scroll` sees raw scroll events. Each line printed says which
    of the two received what, so it can be read off which gestures reach Python at all, and
    with which sign, before deciding how the viewer maps gestures to panning and zooming.
    Stays open like `run_keyboard`, for the same reason.
    """
    page.title = "jiyuu — flet_check (gestures)"
    containers: list[ft.Control] = [
        ft.Container(
            content=ft.Text(f"Node {i}"),
            left=(i % 10) * 120,
            top=(i // 10) * 60,
            bgcolor=ft.Colors.BLUE_100,
            padding=8,
        )
        for i in range(100)
    ]
    stack = ft.Stack(controls=containers, width=10 * 120, height=10 * 60)

    def on_scroll(event: ft.ScrollEvent) -> None:
        print(f"G scroll: delta=({event.scroll_delta.x:+.1f}, {event.scroll_delta.y:+.1f})", flush=True)

    def on_interaction_start(event: ft.ScaleStartEvent) -> None:
        print(f"V start: pointers={event.pointer_count}", flush=True)

    ctrl = {"held": False}

    async def on_interaction_update(event: ft.ScaleUpdateEvent) -> None:
        print(
            f"V update: pointers={event.pointer_count} scale={event.scale:.3f} "
            f"focal_delta=({event.focal_point_delta.x:+.1f}, {event.focal_point_delta.y:+.1f}) "
            f"ctrl={ctrl['held']}",
            flush=True,
        )
        # Ctrl + two-finger vertical move zooms: each pixel moved changes the scale by 1%.
        # The sign was checked by hand on a trackpad with natural scrolling; the opposite
        # sign, tried first, zoomed the wrong way there.
        if ctrl["held"] and event.pointer_count == 2 and event.focal_point_delta.y:
            await viewer.zoom(1 + event.focal_point_delta.y * 0.01)

    def is_ctrl(key: str) -> bool:
        return key.startswith("Control")

    def on_key_down(event: ft.KeyDownEvent) -> None:
        print(f"K down: {event.key!r}", flush=True)
        if is_ctrl(event.key) and not ctrl["held"]:
            ctrl["held"] = True
            viewer.pan_enabled = False
            viewer.update()

    def on_key_up(event: ft.KeyUpEvent) -> None:
        print(f"K up: {event.key!r}", flush=True)
        if is_ctrl(event.key):
            ctrl["held"] = False
            viewer.pan_enabled = True
            viewer.update()

    viewer = ft.InteractiveViewer(
        content=stack,
        constrained=False,
        boundary_margin=ft.Margin.all(2000),
        trackpad_scroll_causes_scale=False,
        min_scale=0.25,
        max_scale=4.0,
        interaction_update_interval=50,
        on_interaction_start=on_interaction_start,
        on_interaction_update=on_interaction_update,
        on_size_change=lambda event: print(
            f"S viewer size: {event.width:.0f} x {event.height:.0f}", flush=True
        ),
    )
    closed = {"value": False}

    def on_disconnect(_) -> None:
        closed["value"] = True

    page.on_disconnect = on_disconnect
    page.add(
        ft.Text(
            "Two-finger move pans. Hold Ctrl and move two fingers up or down to zoom. "
            "Watch which way it zooms, and whether the map drifts sideways while it does."
        ),
        # The Container is what fills the window: KeyboardListener is not a layout control,
        # so `expand` on it is not honoured, and the map inside it was left with no visible
        # size at all when it was relied on.
        ft.Container(
            expand=True,
            content=ft.KeyboardListener(
                content=ft.GestureDetector(content=viewer, on_scroll=on_scroll),
                autofocus=True,
                on_key_down=on_key_down,
                on_key_up=on_key_up,
            ),
        ),
    )
    page.update()

    waited = 0.0
    while not closed["value"] and waited < KEYBOARD_CHECK_TIMEOUT:
        await asyncio.sleep(0.5)
        waited += 0.5
    print("check ended (window closed or timed out)")


async def run_transform(page: ft.Page) -> None:
    """Pan and zoom by setting the map's position and scale directly, without
    `InteractiveViewer`.

    The map is a `Stack` inside another `Stack` that fills the window: its `left`/`top` is
    the view's offset and its `scale` (around its own top-left corner) is the view's scale,
    so a content point `p` appears on screen at `offset + scale * p`. A `GestureDetector`'s
    scale events, which a trackpad's two-finger move and a click-and-drag both produce, set
    all three together and send them in one update — so a zoom around the pointer, which
    changes the scale and the offset at once, reaches the screen as one change rather than
    as two `InteractiveViewer` calls with a frame drawn in between. Stays open like
    `run_keyboard`.
    """
    page.title = "jiyuu — flet_check (transform)"
    containers: list[ft.Control] = [
        ft.Container(
            content=ft.Text(f"Node {i}"),
            left=(i % 10) * 120,
            top=(i // 10) * 60,
            bgcolor=ft.Colors.BLUE_100,
            padding=8,
        )
        for i in range(100)
    ]
    view = {"x": 20.0, "y": 20.0, "scale": 1.0}
    content = ft.Stack(
        controls=containers,
        width=10 * 120,
        height=10 * 60,
        left=view["x"],
        top=view["y"],
        scale=ft.Scale(scale=1.0, alignment=ft.Alignment.TOP_LEFT),
    )
    ctrl = {"held": False}

    def apply() -> None:
        content.left, content.top = view["x"], view["y"]
        content.scale = ft.Scale(scale=view["scale"], alignment=ft.Alignment.TOP_LEFT)
        content.update()

    def on_scale_update(event: ft.ScaleUpdateEvent) -> None:
        if ctrl["held"] and event.pointer_count == 2:
            # Zoom around the gesture's focal point (the pointer), in window coordinates:
            # the content point under it stays under it.
            factor = 1 + event.focal_point_delta.y * 0.01
            new_scale = min(4.0, max(0.25, view["scale"] * factor))
            ratio = new_scale / view["scale"]
            focal = event.local_focal_point
            view["x"] = focal.x - (focal.x - view["x"]) * ratio
            view["y"] = focal.y - (focal.y - view["y"]) * ratio
            view["scale"] = new_scale
        else:
            view["x"] += event.focal_point_delta.x
            view["y"] += event.focal_point_delta.y
        apply()

    def on_key_down(event: ft.KeyDownEvent) -> None:
        if event.key.startswith("Control"):
            ctrl["held"] = True

    def on_key_up(event: ft.KeyUpEvent) -> None:
        if event.key.startswith("Control"):
            ctrl["held"] = False

    closed = {"value": False}

    def on_disconnect(_) -> None:
        closed["value"] = True

    page.on_disconnect = on_disconnect
    page.add(
        ft.Text("Two-finger move or click-and-drag pans; Ctrl + two fingers up/down zooms."),
        ft.Container(
            expand=True,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.KeyboardListener(
                autofocus=True,
                on_key_down=on_key_down,
                on_key_up=on_key_up,
                content=ft.GestureDetector(
                    on_scale_update=on_scale_update,
                    content=ft.Stack(
                        controls=[content],
                        on_size_change=lambda event: print(
                            f"S view size: {event.width:.0f} x {event.height:.0f}", flush=True
                        ),
                    ),
                ),
            ),
        ),
    )
    page.update()

    waited = 0.0
    while not closed["value"] and waited < KEYBOARD_CHECK_TIMEOUT:
        await asyncio.sleep(0.5)
        waited += 0.5
    print("check ended (window closed or timed out)")


def main() -> None:
    """Dispatch to one of the checks above, by the first command-line argument."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    runners = {
        "auto": run_auto,
        "keyboard": run_keyboard,
        "gestures": run_gestures,
        "transform": run_transform,
    }
    if mode not in runners:
        print(f"unknown mode {mode!r}; use one of {', '.join(runners)}", file=sys.stderr)
        sys.exit(1)
    ft.run(runners[mode])


if __name__ == "__main__":
    main()
