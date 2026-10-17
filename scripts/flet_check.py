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


def main() -> None:
    """Dispatch to `run_auto` or `run_keyboard` based on the first command-line argument."""
    mode = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if mode == "auto":
        ft.run(run_auto)
    elif mode == "keyboard":
        ft.run(run_keyboard)
    else:
        print(f"unknown mode {mode!r}; use 'auto' or 'keyboard'", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
