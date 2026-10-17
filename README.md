# jiyuu

A mindmap viewer and editor, similar to FreeMind and Freeplane, written in Python with
[Flet](https://flet.dev). It opens FreeMind/Freeplane `.mm` files and stores its own maps as
`.ink` files — a plain text format with a YAML header, editable with any text editor.

## Install

```bash
poetry install
```

## Run

```bash
poetry run jiyuu version
```

## Development

```bash
poetry run pytest
poetry run pylint --rcfile=.github/workflows/pylintrc --fail-under=9.5 jiyuu
poetry run ty check
```

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE).
