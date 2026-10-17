"""A map's tree as the text of an `.ink` file's `ink:body` section: an indented list.

Each node is one line: two spaces per level of depth, `- `, then the node's text. The
root is the first line, at no indentation:

    - Project
      - Goals
        - I/O
      - Risks

Every line starts with spaces or `-`, so a body written here can never contain a line that
reads as an `.ink` section fence (which starts with `=====`).
"""

from __future__ import annotations

from ..model import Node

#: What one level of depth is indented by.
INDENT = "  "
#: What comes before a node's text on its line.
MARKER = "- "


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
