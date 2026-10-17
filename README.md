# jiyuu

A mindmap viewer, similar to FreeMind and Freeplane, written in Python with
[Flet](https://flet.dev). It opens FreeMind/Freeplane `.mm` files and draws them with the root
in the middle and its branches growing to the left and right, in one of several colour themes.

## Install

```bash
poetry install
```

## Run

```bash
poetry run jiyuu open path/to/map.mm                       # in the default theme
poetry run jiyuu open path/to/map.mm --theme solarized-dark
poetry run jiyuu check path/to/map.mm                      # list what could not be read
```

The bundled themes are `tokyonight-night` (the default), `nord`, `nord-frost`, `nord-aurora`
and `solarized-dark`; `--theme` also takes a path to a theme file of your own, in the format
described in [`jiyuu/assets/themes/README.md`](jiyuu/assets/themes/README.md).

In the window:

| Action | Does |
|---|---|
| Two-finger move, or click and drag | Pan |
| Arrow keys | Move the selection |
| Space | Fold or unfold the selected node |
| Click a node | Select it |
| Ctrl + two-finger move up or down | Zoom |
| Click the circle beside a node | Fold or unfold its branch; a folded branch's circle shows how many nodes it hides |
| Escape | Select the root, and go back to 100% with it in the middle of the window |

## Development

```bash
poetry run pytest
poetry run pylint --rcfile=.github/workflows/pylintrc --fail-under=9.5 jiyuu
poetry run ty check
```

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). The bundled font and the colour themes' palettes
come with licences of their own: see [`jiyuu/assets/DejaVuSans-LICENSE.txt`](jiyuu/assets/DejaVuSans-LICENSE.txt)
and [`jiyuu/assets/themes/README.md`](jiyuu/assets/themes/README.md).
