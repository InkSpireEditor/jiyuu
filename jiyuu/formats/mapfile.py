"""A map stored as an `.ink` file: `ink:meta`, the tree in `ink:body`, and per-node
metadata in `ink:nodes`.

    ===== ink:meta
    kind: mindmap
    ===== ink:body
    - Project
      - Goals
      - Risks
    ===== ink:nodes
    "7be48fc73f0ebe9c": {side: "right"}
    "32a21dfedf2cf99c": {side: "left", folded: "true"}

The file's sections are read by `ink`, its body by `body`. `ink:nodes` holds one line per
node that has anything to record, keyed by the node's id (`model.node_id` of its
`model.path_of`), in body order. Two keys mean something here:

- `side`: `"left"` or `"right"`, on a child of the root only. It is written for every child
  of the root whose side is decided, so reopening a file never depends on the layout
  deciding the sides again.
- `folded`: `"true"` on a folded node. An unfolded node has no `folded` key at all.

Any other key in an entry is kept on the node (`Node.extra`) and written back with it.

An entry whose key matches no node — the node was renamed or moved in a text editor since
the file was written — is not applied, and is not written again: the node it described
gets the defaults (unfolded, side decided by the layout). Nothing in the tree depends on
`ink:nodes`, so losing an entry this way never loses node text.

Every key and value in `ink:nodes` is written quoted, and read back with
`yaml.BaseLoader`, which reads every scalar as a string whether quoted or not. Some ids are
sixteen decimal digits (`"1984891675846323"`); a YAML loader that resolves scalars would
read such a key unquoted as an integer, which would then match no node.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..model import MindMap, Node, node_id, path_of, walk
from . import body, ink
from .ink import WARNING, Problem

#: The `ink:meta` key and value that mark a `.ink` file as a map.
KIND_KEY = "kind"
KIND = "mindmap"


def _fence_line_number(text: str, name: str) -> int:
    """The line number of the last fence opening section `name` in `text`, or `0` if no
    fence opens it. The last, because a section opened twice keeps its last occurrence."""
    numbers = [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if ink.section_name(line) == name
    ]
    return numbers[-1] if numbers else 0


def read_nodes_section(text: str) -> tuple[dict[str, dict[str, str]], list[Problem]]:
    """The entries in an `ink:nodes` section's `text`, by node id, and every problem found.

    Problems are numbered by line within `text`, from 1. Text that is not YAML, or not a
    mapping, gives no entries at all. An entry whose value is not a mapping, or a field
    whose value is not a single string, is left out and reported.
    """
    try:
        loaded = yaml.load(text, Loader=yaml.BaseLoader)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + 1 if mark is not None else 1
        return {}, [Problem(line, WARNING, "the nodes section is not valid YAML; every node gets defaults")]
    if loaded is None:
        return {}, []
    if not isinstance(loaded, dict):
        return {}, [Problem(1, WARNING, "the nodes section is not a mapping; every node gets defaults")]

    entries: dict[str, dict[str, str]] = {}
    problems: list[Problem] = []
    for key, fields in loaded.items():
        if not isinstance(fields, dict):
            problems.append(Problem(1, WARNING, f"the nodes entry {key!r} is not a mapping; ignored"))
            continue
        kept = {name: value for name, value in fields.items() if isinstance(value, str)}
        for name in fields.keys() - kept.keys():
            problems.append(
                Problem(1, WARNING, f"the field {name!r} of nodes entry {key!r} is not a string; ignored")
            )
        entries[key] = kept
    return entries, problems


def render_nodes_section(entries: dict[str, dict[str, str]]) -> str:
    """`entries` as the text of an `ink:nodes` section: one line per entry, in the order
    given, every key and value quoted by `json.dumps`, which YAML reads as a quoted string."""
    lines = []
    for key, fields in entries.items():
        mapping = ", ".join(f"{name}: {json.dumps(value)}" for name, value in fields.items())
        lines.append(f"{json.dumps(key)}: {{{mapping}}}\n")
    return "".join(lines)


def apply_nodes_section(root: Node, entries: dict[str, dict[str, str]]) -> None:
    """Sets every node under `root` from its entry in `entries`, or to the defaults if it
    has none.

    A `side` other than `"left"` or `"right"` is read as undecided, as if it were absent.
    """
    for node in walk(root):
        fields = entries.get(node_id(path_of(node, root)), {})
        side = fields.get("side")
        node.side = side if side in ("left", "right") else None
        node.folded = fields.get("folded") == "true"
        node.extra = {name: value for name, value in fields.items() if name not in ("side", "folded")}


def build_nodes_section(root: Node) -> dict[str, dict[str, str]]:
    """The `ink:nodes` entries for every node under `root` that has anything to record, in
    body order, keyed by node id."""
    entries: dict[str, dict[str, str]] = {}
    for node in walk(root):
        fields = dict(node.extra)
        if node in root.children and node.side is not None:
            fields["side"] = node.side
        if node.folded:
            fields["folded"] = "true"
        if fields:
            entries[node_id(path_of(node, root))] = fields
    return entries


def _kind_problems(text: str, document: ink.Document) -> list[Problem]:
    """A warning when `text` is not marked as a map: its `kind` names something else, or it
    has no fences at all and so no `meta` to say what it is."""
    kind = document.metadata.get(KIND_KEY)
    if kind is not None and kind != KIND:
        return [Problem(1, WARNING, f"ink:meta says kind: {kind}, not {KIND}; read as a map anyway")]
    if kind is None and document.body == text:
        return [Problem(1, WARNING, f"no ink:meta '{KIND_KEY}: {KIND}'; read as a map anyway")]
    return []


def read(text: str) -> tuple[MindMap | None, list[Problem]]:
    """The map in `.ink` file `text`, and every problem found reading it.

    The tree comes from the body, with each node's folding, side and other fields from
    `ink:nodes`. `meta` becomes `MindMap.meta`, with `kind: mindmap` added if missing, and
    every section other than `body` and `nodes` is kept as text, to be written back as it
    was. Problems with the sections, the body and `ink:nodes` are numbered by line in the
    whole file, in line order. The map is `None` only when the body holds no tree.
    """
    document = ink.parse(text)
    root, body_problems = body.read(document.body)
    body_offset = 0 if document.body == text else _fence_line_number(text, ink.SECTION_BODY)
    problems = ink.check(text) + _kind_problems(text, document)
    problems += [Problem(p.line + body_offset, p.level, p.message) for p in body_problems]

    if root is not None:
        entries, nodes_problems = read_nodes_section(document.sections.get(ink.SECTION_NODES, ""))
        nodes_offset = _fence_line_number(text, ink.SECTION_NODES)
        problems += [Problem(p.line + nodes_offset, p.level, p.message) for p in nodes_problems]
        apply_nodes_section(root, entries)

    problems.sort(key=lambda problem: (problem.line, problem.level))
    if root is None:
        return None, problems
    meta = dict(document.metadata)
    meta.setdefault(KIND_KEY, KIND)
    other = {name: section for name, section in document.sections.items() if name != ink.SECTION_NODES}
    return MindMap(root=root, meta=meta, other_sections=other), problems


def load(path: Path) -> tuple[MindMap | None, list[Problem]]:
    """The map in the `.ink` file at `path`; see `read`. Raises `OSError` or
    `UnicodeDecodeError` if the file cannot be read as UTF-8 text."""
    return read(path.read_text(encoding="utf-8"))


def dump(mindmap: MindMap) -> str:
    """`mindmap` as the text of an `.ink` file: `meta` (with `kind: mindmap` added if
    missing), the tree as the body, every other section it was read with, and last
    `ink:nodes`, left out when no node has anything to record."""
    meta = dict(mindmap.meta)
    meta.setdefault(KIND_KEY, KIND)
    sections = dict(mindmap.other_sections)
    nodes_text = render_nodes_section(build_nodes_section(mindmap.root))
    if nodes_text:
        sections[ink.SECTION_NODES] = nodes_text
    return ink.render(meta, body.write(mindmap.root), sections)
