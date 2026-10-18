"""Tests for jiyuu's text-measuring classes."""

from pathlib import Path

import pytest

from jiyuu.measure import DEFAULT_FONT_PATH, FixedMeasurer, PillowMeasurer


def test_fixed_measurer_depends_only_on_length() -> None:
    """A `FixedMeasurer`'s answer is exactly `len(text) * width_per_char`, and `height`."""
    measurer = FixedMeasurer(width_per_char=10.0, height=16.0)
    assert measurer.size_of("Goals") == (50.0, 16.0)
    assert measurer.size_of("") == (0.0, 16.0)


def test_pillow_measurer_loads_the_bundled_font() -> None:
    """The bundled font loads and measures real text with it, without naming a system font."""
    measurer = PillowMeasurer()
    width, height = measurer.size_of("Project")
    assert width > 0
    assert height > 0


def test_pillow_measurer_treats_empty_text_as_a_single_space() -> None:
    """Empty text is measured as a space, not as nothing, so a new node still has a width."""
    measurer = PillowMeasurer()
    width, _ = measurer.size_of("")
    assert width > 0


def test_default_font_path_exists() -> None:
    """The font the default measurer loads is bundled with the package, not assumed to be
    installed on whatever machine jiyuu runs on."""
    assert Path(DEFAULT_FONT_PATH).is_file()


def test_pillow_measurer_measures_each_text_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A text measured before is answered without asking the font again."""
    measurer = PillowMeasurer()
    first = measurer.size_of("Project")
    monkeypatch.setattr(measurer._font, "getbbox", None)  # pylint: disable=protected-access
    assert measurer.size_of("Project") == first


def test_pillow_measurer_gives_every_text_the_font_s_line_height() -> None:
    """Empty text, low characters and tall ones are all as tall as one line of the font
    (DejaVu Sans at 16: ascent 15 plus descent 4), whatever height their shapes cover."""
    measurer = PillowMeasurer()
    assert {measurer.size_of(text)[1] for text in ("", "...", "aaa", "Project", "Ag")} == {19}
