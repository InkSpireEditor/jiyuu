# jiyuu

A mindmap viewer, similar to FreeMind and Freeplane, written in Python with
[Flet](https://flet.dev). It opens FreeMind/Freeplane `.mm` files and its own `.ink` files, and
draws them with the root in the middle and its branches growing to the left and right, in one
of several colour themes.

An `.ink` map is plain text, editable in any text editor: a `meta` section, the tree as an
indented list, then a `nodes` section recording which side of the root each branch is drawn
on and which nodes are folded. Opening a `.mm` file writes a `.ink` copy of it beside it,
unless one is already there:

```
===== ink:meta
kind: mindmap
===== ink:body
- Project
  - Goals
  - Risks
===== ink:nodes
"7be48fc73f0ebe9c": {side: "right", folded: "true"}
"32a21dfedf2cf99c": {side: "left"}
```

Each `nodes` line is keyed by an id computed from the node's text and the text of the nodes
above it. Renaming or moving a node in a text editor changes its id, so its line no longer
applies: the node opens unfolded, and its side is chosen again.

## Install

```bash
poetry install
```

## Run

```bash
poetry run jiyuu open path/to/map.mm                       # in the default theme
poetry run jiyuu open path/to/map.ink --theme solarized-dark
poetry run jiyuu check path/to/map.ink                     # list problems; fails on an error
poetry run jiyuu export --mm path/to/map.ink path/to/map.mm # write a Freeplane .mm file
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
| F2 | Edit the selected node's text |
| Typing a character | Replace the selected node's text, starting with that character |
| Enter, while editing text | Keep the text typed; clicking outside the text does the same |
| Escape, while editing text | Leave the node's text as it was |
| Insert or Tab | Add a child to the selected node, and edit its text |
| Enter | Add a sibling after the selected node, and edit its text |
| Delete | Delete the selected node and its branch |
| Ctrl + Up or Down | Move the selected node up or down among its siblings |
| Ctrl + the arrow towards the root | Move the selected node up one level; on a node directly under the root, move it to the root's other side |
| Ctrl+Z | Undo the latest change, folds included |
| Ctrl+Y, Ctrl+Shift+Z | Redo |

The File menu above the map exports it as a Freeplane `.mm` file, to a new file whose name
you type; an existing file is never written over. `jiyuu export` does the same from the
command line, and replaces an existing file only with `--overwrite`.

Changes are saved automatically, 1.5 seconds after the last one, to the `.ink` file the
map was opened from. A `.mm` file is never written: opening one writes a `.ink` copy beside
it, and changes are saved there; if that `.ink` already exists, the window asks for another
name at the first change. If the file is changed by another program while the map is open, a
banner appears within about a second, and nothing more is saved until you choose to reload
the file or to keep the window's version over it.

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
