"""Measures how much space a node's text needs, before anything draws it.

jiyuu's layout reserves space for a node's box ahead of asking Flet to render it, so it needs
a prediction of the text's size that does not depend on anything already being on screen.
`PillowMeasurer` is that prediction, backed by the Pillow imaging library's own font metrics;
`FixedMeasurer` is a deterministic stand-in for tests that would otherwise depend on exactly
which font is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from os import PathLike
from typing import Protocol

from PIL import ImageFont

#: Bundled with jiyuu so its layout does not depend on any particular font being installed
#: on the machine it runs on. Licensed under the Bitstream Vera licence (DejaVu's own changes
#: to it are public domain); see `DejaVuSans-LICENSE.txt` alongside it.
DEFAULT_FONT_PATH: str = str(resources.files("jiyuu").joinpath("assets", "DejaVuSans.ttf"))
DEFAULT_FONT_SIZE = 16


class Measurer(Protocol):
    """Something that can predict the size `text` alone would need, with no padding."""

    def size_of(self, text: str) -> tuple[float, float]:
        """`(width, height)` text would need, in logical pixels, not counting any padding."""


class PillowMeasurer:
    """Predicts a string's rendered size from a TrueType font's own metrics, via Pillow.

    The font is loaded once, in `__init__`, rather than on every call to `size_of`. Each
    size is also kept once measured: the window lays a map out again on every fold, and
    asking Pillow for the size of hundreds of unchanged strings each time takes a large part
    of a second on a map of several hundred nodes.
    """

    def __init__(
        self, font_path: str | PathLike[str] = DEFAULT_FONT_PATH, size: float = DEFAULT_FONT_SIZE
    ) -> None:
        self._font = ImageFont.truetype(font_path, size)
        self._sizes: dict[str, tuple[float, float]] = {}

    def size_of(self, text: str) -> tuple[float, float]:
        """`(width, height)` Pillow predicts for `text` in this font.

        An empty string is measured as a single space instead of as nothing, so a node with
        no text yet — one just created, waiting to be typed into — still gets a box with
        some width to it rather than collapsing to zero.
        """
        size = self._sizes.get(text)
        if size is None:
            left, top, right, bottom = self._font.getbbox(text or " ")
            size = self._sizes[text] = (right - left, bottom - top)
        return size


@dataclass
class FixedMeasurer:
    """A `Measurer` whose answer depends only on a string's length, for tests that need a
    size they can compute by hand rather than one that depends on an installed font."""

    width_per_char: float
    height: float

    def size_of(self, text: str) -> tuple[float, float]:
        """`(len(text) * width_per_char, height)` — ignores what the characters actually are."""
        return (len(text) * self.width_per_char, self.height)
