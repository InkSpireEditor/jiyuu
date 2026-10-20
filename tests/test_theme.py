"""Tests for jiyuu's colour themes."""

from pathlib import Path

import pytest

from jiyuu.theme import (
    DEFAULT_THEME,
    Colors,
    ThemeError,
    available_themes,
    contrast_ratio,
    load_theme,
)

#: The lowest contrast any text, or any edge against its canvas, may have in a bundled theme:
#: the WCAG 2 AA threshold for large text and for non-text graphics.
CONTRAST_FLOOR = 3.0

VALID = """\
name: Test
canvas: "#000000"
edge: "#ffffff"
selection: {text: "#000000", background: "#ffffff"}
root: {text: "#ffffff", background: "#000000"}
task_done: {text: "#888888", background: "#000000"}
urgent: {text: "#ffffff", background: "#cc0000"}
levels:
  - {text: "#000000", background: "#ffffff"}
  - {text: "#ffffff", background: "#000000"}
"""


def _write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "theme.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_the_five_bundled_themes_are_available_and_the_default_is_one_of_them() -> None:
    """Exactly the five bundled themes are listed, and the default is among them."""
    assert available_themes() == [
        "nord",
        "nord-aurora",
        "nord-frost",
        "solarized-dark",
        "tokyonight-night",
    ]
    assert DEFAULT_THEME in available_themes()


@pytest.mark.parametrize("name", available_themes())
def test_every_bundled_theme_is_readable(name: str) -> None:
    """Every text colour in a bundled theme contrasts with its background by at least the
    floor, and so does its edge colour with its canvas."""
    theme = load_theme(name)
    pairs = [("root", theme.root), ("selection", theme.selection), ("task_done", theme.task_done), ("urgent", theme.urgent)] + [
        (f"levels[{i}]", level) for i, level in enumerate(theme.levels)
    ]
    for label, pair in pairs:
        ratio = contrast_ratio(pair.text, pair.background)
        assert ratio >= CONTRAST_FLOOR, f"{name} {label}: {ratio:.2f}"
    assert contrast_ratio(theme.edge, theme.canvas) >= CONTRAST_FLOOR


def test_for_depth_uses_root_then_cycles_through_levels(tmp_path: Path) -> None:
    """Depth 0 is the root; depth 1 is the first level; past the last level, back to the
    first."""
    theme = load_theme(_write(tmp_path, VALID))
    assert theme.for_depth(0) == theme.root
    assert theme.for_depth(1) == theme.levels[0]
    assert theme.for_depth(2) == theme.levels[1]
    assert theme.for_depth(3) == theme.levels[0]


def test_a_theme_file_outside_the_package_loads_like_a_bundled_one(tmp_path: Path) -> None:
    """A path to any theme file works, not only a bundled theme's name."""
    theme = load_theme(_write(tmp_path, VALID))
    assert theme.name == "Test"
    assert theme.levels == (Colors("#000000", "#ffffff"), Colors("#ffffff", "#000000"))
    assert theme.task_done == Colors("#888888", "#000000")


def test_contrast_ratio_of_known_pairs() -> None:
    """Black on white is the maximum, 21; a colour against itself is the minimum, 1."""
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0)
    assert contrast_ratio("#81a1c1", "#81a1c1") == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (VALID.replace('canvas: "#000000"\n', ""), "missing 'canvas'"),
        (VALID.replace('task_done: {text: "#888888", background: "#000000"}\n', ""), "'task_done' must be a mapping"),
        (VALID.replace('"#000000"', "#000000", 1), "not a \"#rrggbb\" colour"),
        (VALID.replace('canvas: "#000000"', 'canvas: "black"'), "not a \"#rrggbb\" colour"),
        (VALID.split("levels:", maxsplit=1)[0] + "levels: []\n", "non-empty list"),
        ("- just\n- a list\n", "YAML mapping"),
        (VALID.replace('root: {text: "#ffffff", background: "#000000"}', 'root: "#000000"'), "mapping"),
    ],
    ids=["missing key", "missing task_done", "unquoted colour", "named colour", "empty levels", "not a mapping", "pair not a mapping"],
)
def test_an_unusable_theme_file_is_refused_with_its_reason(
    tmp_path: Path, text: str, expected: str
) -> None:
    """Each kind of broken theme file raises `ThemeError` naming what is wrong with it."""
    with pytest.raises(ThemeError, match=expected):
        load_theme(_write(tmp_path, text))


def test_a_missing_theme_file_is_refused(tmp_path: Path) -> None:
    """A name that is neither a bundled theme nor an existing file raises `ThemeError`."""
    with pytest.raises(ThemeError, match="cannot be read"):
        load_theme(str(tmp_path / "nowhere.yaml"))


def test_invalid_yaml_is_refused(tmp_path: Path) -> None:
    """A file that is not YAML at all raises `ThemeError`, not a raw parser error."""
    with pytest.raises(ThemeError, match="not valid YAML"):
        load_theme(_write(tmp_path, "levels: [unclosed\n"))
