# jiyuu

A mind map viewer and editor, in the style of FreeMind and Freeplane, written in Python with
[Flet](https://flet.dev). It opens FreeMind/Freeplane `.mm` files and its own `.ink` files,
draws them with the root in the middle and branches growing to the left and right, and saves
every change as it is made.

![jiyuu showing docs/example.ink](docs/screenshot.png)

The map above is [`docs/example.ink`](docs/example.ink); after installing, open it with
`jiyuu docs/example.ink`.

jiyuu is part of the [InkSpireEditor](https://github.com/InkSpireEditor) projects. It is
tested on Linux only.

## Install

jiyuu needs [uv](https://docs.astral.sh/uv/), which also provides a suitable Python (3.12 or
newer) if the system has none. From a clone of this repository:

```bash
git clone https://github.com/InkSpireEditor/jiyuu.git
cd jiyuu
scripts/install.sh              # for the current user, in ~/.local/bin
scripts/install.sh --system     # or for every user, in /usr/local/bin (uses sudo)
scripts/install.sh --uninstall  # remove it again
```

The script installs jiyuu in an environment of its own, with its dependencies at the versions
recorded in `uv.lock`, and asks no questions. Running it again updates jiyuu from the clone.

Without a clone, `uv tool install git+https://github.com/InkSpireEditor/jiyuu` installs the
latest version, with its dependencies at the newest versions allowed by `pyproject.toml`.

jiyuu's window is drawn by Flet's desktop client, which is downloaded from Flet's GitHub
releases into `~/.flet/client` (about 40 MB once unpacked) once per user: by the script, for
a user install, and otherwise the first time a map is opened.

## Use

```bash
jiyuu path/to/map.ink                                # open a map; same as `jiyuu open …`
jiyuu path/to/map.mm --theme solarized-dark          # in another colour theme
jiyuu check path/to/map.ink                          # list problems; fails on an error
jiyuu export --mm path/to/map.ink path/to/map.mm     # write a Freeplane .mm file
jiyuu task-sync path/to/map.ink                      # sync its tasks with taskwarrior
```

A file whose name is also a command's, such as `check`, is opened with `jiyuu ./check`.
`jiyuu` alone, or with a first argument that is neither a command nor an existing file,
prints the help.

The bundled themes are `tokyonight-night` (the default), `nord`, `nord-frost`, `nord-aurora`
and `solarized-dark`. `--theme` also takes the path of a theme file of your own, in the
format described in [`jiyuu/assets/themes/README.md`](jiyuu/assets/themes/README.md).

### Moving around

| Action | Does |
|---|---|
| Two-finger move, or click and drag | Pan |
| Ctrl + two-finger move up or down | Zoom, around the pointer |
| Arrow keys | Move the selection. On the right side, Right goes away from the root and Left towards it; on the left side, the reverse. Up and Down move between siblings |
| Click a node | Select it |
| Space | Fold or unfold the selected node |
| Click the circle beside a node | Fold or unfold its branch; a folded branch's circle shows how many nodes it hides |
| Escape | Select the root, and go back to 100% with it in the middle of the window |

### Editing

| Key | Does |
|---|---|
| F2 | Edit the selected node's text |
| Typing a character | Replace the selected node's text, starting with that character |
| Enter, while editing text | Keep the text typed; clicking outside the text does the same |
| Escape, while editing text | Leave the node's text as it was |
| Insert or Tab | Add a child to the selected node, and edit its text |
| Enter | Add a sibling after the selected node, and edit its text |
| Delete | Delete the selected node and its branch |
| Ctrl + Up or Down | Move the selected node up or down among its siblings |
| Ctrl + the arrow towards the root | Move the selected node up one level; on a node directly under the root, move it to the root's other side |
| Ctrl+T | Make the selected node a task, with a due date and a priority, or change them; on a task, "Not a task" makes it a plain node again |
| Ctrl+D, or a click on a task's checkbox | Tick the task done, or untick it |
| Ctrl+Z | Undo the latest change, folds included |
| Ctrl+Y, Ctrl+Shift+Z | Redo |

### Saving

There is no Save command: every change, folds included, is saved 1.5 seconds after the last
one, to the `.ink` file the map was opened from.

A `.mm` file is never written to. Opening one writes a `.ink` copy beside it, and changes are
saved to that copy. If the copy already exists, it may hold changes made the last time the
`.mm` was opened, so it is left untouched, and at the first change the window asks for the
name of a new file instead.

If another program changes the file while the map is open, the window reads it again within
about a second, if it has no unsaved change and no text or task dialog is open; the node
selected stays selected. Otherwise a banner appears, and nothing more is saved until you
choose to reload the file, dropping the window's unsaved changes, or to keep the window's
version, writing it over the file.

The File menu above the map exports it as a Freeplane `.mm` file, to a new file whose name
you type; an existing file is never written over. `jiyuu export` does the same from the
command line, and replaces an existing file only with `--overwrite`.

## Tasks and taskwarrior

A node becomes a task with Ctrl+T, which also sets its due date and its priority (H, M or
L). The due date is typed as `2026-10-25` or `2026-10-25T14:00`, or as anything
[taskwarrior](https://taskwarrior.org) understands, such as `tomorrow`, `friday` or `eow`,
which is turned into a date when the dialog is saved. Ctrl+D, or a click on the checkbox,
ticks a task done.

Each task is kept as a task in taskwarrior 2.6 or later, so that `task` and taskwarrior-tui
list it, with the map's file name as its project: `task project:map list` lists the tasks of
`map.ink`. Each task also records the map's full path in an attribute `jiyuumap`. An open
window syncs its map with taskwarrior after each save and every minute;
`jiyuu task-sync map.ink` does the same for a map that is not open, and can be run from
cron:

```
*/10 * * * * jiyuu task-sync /home/me/maps/map.ink
```

What a sync does:

| Change | In the other place |
|---|---|
| A node made a task | The task is created in taskwarrior |
| A task's text, due date or priority changed in the map | Changed in taskwarrior |
| The same changed in taskwarrior (`task modify`, taskwarrior-tui) | Changed in the map |
| Changed in both since the last sync | The later change is kept |
| Ticked done in the map | Completed in taskwarrior, as `task done` |
| Completed in taskwarrior | Ticked done in the map, drawn greyed and struck through |
| Unticked in either | Pending again in the other |
| A task node deleted in the map, or made a plain node | Deleted in taskwarrior, as `task delete` |
| Deleted in taskwarrior | The node, and its branch, deleted from the map |

A sync changes only what the map sets in a task: its description, status, due date, priority,
project and `jiyuumap`. Tags, annotations and anything else added in taskwarrior are kept. A
task created in taskwarrior is not added to any map.

A task that taskwarrior finds urgent is drawn in red: one whose urgency is at least 9, the
urgency taskwarrior gives a task due today with no priority, or the value set with
`task config jiyuu.urgent 12`. The window reads that value when it opens.

A task is matched to its taskwarrior task through the `nodes` section of the map's file (see
below). A task renamed or moved in a text editor is matched again if its text is unchanged;
renamed by hand, it becomes a new task in taskwarrior at the next sync, and its old task is
deleted. Renaming it in the window, or in taskwarrior, keeps the same task.

## The `.ink` format

An `.ink` map is plain text, readable and editable in any text editor: a `meta` section, the
tree as an indented list, then a `nodes` section recording which side of the root each branch
is drawn on, which nodes are folded, and which taskwarrior task each task is kept in.

```
===== ink:meta
kind: mindmap
===== ink:body
- Project
  - Goals
    - Foo
    - Bar
  - Risks
===== ink:nodes
"7be48fc73f0ebe9c": {side: "right", folded: "true"}
"32a21dfedf2cf99c": {side: "left"}
```

A node can be a task. Its line then starts with a checkbox, as in a Markdown task list, and
can end with a due date and a priority, two spaces after the text:

```
  - Goals
    - [ ] Foo  due:2026-10-25 priority:H
    - [x] Bar
```

`[ ]` is a task not done, `[x]` one that is done, drawn greyed and struck through. In the
window, a task is drawn with ☐ or ☑ before its text, and its due date and priority after it:
`☐ Foo · 2026-10-25 · H`. `due:`
takes a date, `2026-10-25`, or a date and a time, `2026-10-25T14:00`; `priority:` takes `H`,
`M` or `L`. Either can be left out. A node that is not a task, but whose text starts with
`[ ]`, `[x]` or a backslash, is written with a backslash in front: `- \[ ] not a task`. On a
task's line, words at the end of the text that start with `due:` or `priority:` are written
with a backslash before the colon, `due\:soon`, so that they are not read as fields. The
root cannot be a task.

Each `nodes` line is keyed by an id computed from the node's text and the text of the nodes
above it. Renaming or moving a node in a text editor changes its id, so its line no longer
applies: the node opens unfolded, and its side is chosen again.

The section syntax is that of [inkspire-api](https://github.com/InkSpireEditor/inkspire-api)'s
`.ink` files (see its `docs/ink-format.md`); jiyuu's copy of the grammar is in
[`jiyuu/formats/ink.py`](jiyuu/formats/ink.py). jiyuu writes `kind: mindmap` in the `meta`
section, to tell a map apart from other `.ink` files.

## Limitations

- Zooming needs a trackpad: hold Ctrl and move two fingers up or down. There is no zoom by
  mouse wheel or by keyboard yet.
- Maps are opened from the command line only. Flet's file picker needs Zenity on Linux, so
  there is no Open dialog, and the name of a file to export to or save as is typed.
- jiyuu receives the key pressed, not the character it types. The character that starts
  editing a node's text is worked out from the key's name and Shift: it is right for
  letters, and can be wrong for a key whose shifted character differs from its name, such as
  the digit row of an AZERTY keyboard. Every character after it is typed normally.
- Node text is one line. Notes, icons, links and styles from Freeplane maps are not read,
  and so are not written back by an export.

## Development

```bash
uv sync
uv run jiyuu path/to/map.ink
uv run pytest
uv run pylint --rcfile=.github/workflows/pylintrc --fail-under=9.5 jiyuu
uv run ty check
```

## Licence

[PolyForm Noncommercial 1.0.0](LICENSE). The bundled font and the colour themes' palettes
come with licences of their own: see
[`jiyuu/assets/DejaVuSans-LICENSE.txt`](jiyuu/assets/DejaVuSans-LICENSE.txt) and
[`jiyuu/assets/themes/README.md`](jiyuu/assets/themes/README.md).
