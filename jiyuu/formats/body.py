"""A map's tree as the text of an `.ink` file's `ink:body` section: an indented list.

Each node is one line: two spaces per level of depth, `- `, then the node's text. The
root is the first line, at no indentation:

    - Project
      - Goals
        - I/O
      - Risks

`write` always writes exactly that form. Every line starts with spaces or `-`, so a body
written here can never contain a line that reads as an `.ink` section fence (which starts
with `=====`).

`read` accepts more than `write` produces, since a body may have been edited by hand in
any text editor: `*` or `+` as the marker, any indentation width, tabs, blank lines. A
line's depth comes from comparing its indentation with the lines above it — deeper than
the line above makes it a child, the same as a sibling, shallower closes back to the
nearest line at that indentation or less — so four-space or tab indentation reads into
the same tree as two-space. Reading never drops a line's text: a line it cannot place
where it belongs is still attached to the tree, and reported in the list of problems
returned alongside it.
"""

from __future__ import annotations

from .ink import ERROR, WARNING, Problem
from ..model import Node

#: What one level of depth is indented by.
INDENT = "  "
#: What comes before a node's text on its line.
MARKER = "- "
#: The characters `read` accepts as a line's marker.
MARKERS = "-*+"


def _split_line(line: str) -> tuple[str, bool, str]:
    """A line's leading whitespace, whether it has a marker, and its text.

    A marker is one of `MARKERS` followed by a space, or one of them alone on the line —
    which is how an editor that trims trailing spaces leaves a node with empty text,
    written as `- `. Anything else is all text, with no marker.
    """
    stripped = line.lstrip(" \t")
    indentation = line[: len(line) - len(stripped)]
    content = stripped.rstrip()
    if content and content[0] in MARKERS and (len(content) == 1 or content[1] == " "):
        return indentation, True, content[1:].strip()
    return indentation, False, content


def read(text: str) -> tuple[Node | None, list[Problem]]:
    """The tree in body `text`, and every problem found reading it.

    Problems are numbered by line within `text`, from 1. Returns `None` for the tree only
    when `text` has no non-blank line at all.
    """
    lines = [(number, line) for number, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not lines:
        return None, [Problem(1, ERROR, "the body is empty: there is no root node")]

    problems: list[Problem] = []
    root: Node | None = None
    open_nodes: list[tuple[int, Node]] = []  # (indentation, node), root first
    indent_kinds: set[str] = set()  # which of " " and "\t" the indentation has used so far

    for number, line in lines:
        indentation, has_marker, node_text = _split_line(line)
        if not has_marker:
            problems.append(Problem(number, WARNING, "this line has no '-', '*' or '+' marker"))
        if len(indent_kinds) < 2 and len(indent_kinds | set(indentation)) == 2:
            problems.append(Problem(number, WARNING, "tabs and spaces are mixed in the indentation"))
        indent_kinds |= set(indentation)
        depth = len(indentation)
        node = Node(text=node_text)

        if root is None:
            root = node
            open_nodes = [(depth, node)]
            continue

        while len(open_nodes) > 1 and depth <= open_nodes[-1][0]:
            open_nodes.pop()
        parent_depth, parent = open_nodes[-1]
        if depth == parent_depth:  # only the root is open, and this line is level with it
            problems.append(
                Problem(number, ERROR, "a second top-level line; read as a child of the first")
            )
        elif depth < parent_depth:  # only the root is open, and this line is left of it
            problems.append(
                Problem(
                    number,
                    WARNING,
                    "indented less than the root; read as a child of the root",
                )
            )
        parent.children.append(node)
        open_nodes.append((depth, node))

    return root, problems


def write(root: Node) -> str:
    """The tree under `root`, root included, as body text: one line per node, `\\n` line
    endings, a final newline. Folded nodes' children are written too: folding hides a
    branch from view, it does not remove it from the map."""
    lines: list[str] = []

    def emit(node: Node, depth: int) -> None:
        lines.append(f"{INDENT * depth}{MARKER}{node.text}\n")
        for child in node.children:
            emit(child, depth + 1)

    emit(root, 0)
    return "".join(lines)
