"""Colour themes: every colour jiyuu draws a map with, read from a YAML file.

A theme names a colour for each part of a drawn map: the canvas behind it, its edges (also
used for node borders), the selected node, the root, one text/background pair per depth
level below the root, reused from the first once a map is deeper than the theme has levels
for, and a pair for tasks that are done. Themes live in files rather than in code so that one can be changed, or a new one
written, without touching anything else; `jiyuu/assets/themes/README.md` describes the
format and where each bundled theme's colours come from.

`contrast_ratio` computes the WCAG 2 contrast ratio between two colours
(https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio), so that a theme's readability can be
checked rather than judged by eye.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import yaml

#: The theme used when none is asked for.
DEFAULT_THEME = "tokyonight-night"

#: Where the bundled themes are. Each `<name>.yaml` in it is a theme named `<name>`.
THEMES_DIR = Path(str(resources.files("jiyuu").joinpath("assets", "themes")))

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class ThemeError(ValueError):
    """A theme file that cannot be used, and why."""


@dataclass(frozen=True)
class Colors:
    """A text colour and the background it is drawn on."""

    text: str
    background: str


@dataclass(frozen=True)
class Theme:
    """Every colour a map is drawn with. Colours are `"#rrggbb"` strings."""

    name: str
    #: Background behind the whole map.
    canvas: str
    #: Edges between nodes, and the border around each node's box.
    edge: str
    selection: Colors
    root: Colors
    #: One pair per depth below the root: `levels[0]` for depth 1, `levels[1]` for depth 2,
    #: and so on, starting again from `levels[0]` past the last one.
    levels: tuple[Colors, ...]
    #: A task that is done, at any depth.
    task_done: Colors

    def for_depth(self, depth: int) -> Colors:
        """The colours for a node `depth` levels below the root (`0` is the root itself)."""
        if depth == 0:
            return self.root
        return self.levels[(depth - 1) % len(self.levels)]


def contrast_ratio(first: str, second: str) -> float:
    """The WCAG 2 contrast ratio between two `"#rrggbb"` colours, from 1.0 (identical) to
    21.0 (black on white). Which colour is passed first does not matter."""

    def luminance(color: str) -> float:
        channels = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def available_themes() -> list[str]:
    """The names of the bundled themes, sorted."""
    return sorted(path.stem for path in THEMES_DIR.glob("*.yaml"))


def _color(data: dict, key: str, source: Path) -> str:
    """`data[key]`, checked to be a `"#rrggbb"` colour."""
    if key not in data:
        raise ThemeError(f"{source}: missing {key!r}")
    value = data[key]
    if not isinstance(value, str) or not _COLOR.match(value):
        raise ThemeError(f"{source}: {key!r} is {value!r}, not a \"#rrggbb\" colour")
    return value


def _pair(data: dict, key: str, source: Path) -> Colors:
    """`data[key]`, checked to be a mapping with a `text` and a `background` colour."""
    value = data.get(key)
    if not isinstance(value, dict):
        raise ThemeError(f"{source}: {key!r} must be a mapping with 'text' and 'background'")
    return Colors(
        text=_color(value, "text", source),
        background=_color(value, "background", source),
    )


def load_theme(name_or_path: str) -> Theme:
    """The theme named `name_or_path` among the bundled ones, or read from the file at that
    path if it is not one of their names.

    Raises `ThemeError`, naming the file and the problem, for a file that does not exist,
    is not a YAML mapping, is missing a key, holds a colour that is not `"#rrggbb"`, or has
    no levels at all.
    """
    bundled = THEMES_DIR / f"{name_or_path}.yaml"
    source = bundled if bundled.is_file() else Path(name_or_path)
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except OSError as error:
        raise ThemeError(f"{source}: cannot be read ({error})") from error
    except yaml.YAMLError as error:
        raise ThemeError(f"{source}: is not valid YAML ({error})") from error
    if not isinstance(data, dict):
        raise ThemeError(f"{source}: must be a YAML mapping")

    levels = data.get("levels")
    if not isinstance(levels, list) or not levels:
        raise ThemeError(f"{source}: 'levels' must be a non-empty list")

    return Theme(
        name=str(data.get("name", source.stem)),
        canvas=_color(data, "canvas", source),
        edge=_color(data, "edge", source),
        selection=_pair(data, "selection", source),
        root=_pair(data, "root", source),
        levels=tuple(
            _pair({f"levels[{i}]": level}, f"levels[{i}]", source) for i, level in enumerate(levels)
        ),
        task_done=_pair(data, "task_done", source),
    )
