"""Tests for writing a map's tree as an `.ink` body."""

from jiyuu.formats import body, ink
from jiyuu.model import Node


def test_write_indents_two_spaces_per_level_with_a_dash_marker() -> None:
    """The worked example: one line per node, two spaces per level, `- ` before the text,
    a final newline."""
    root = Node(
        text="Project",
        children=[
            Node(text="Goals", children=[Node(text="I/O"), Node(text="TODO"), Node(text="TODO")]),
            Node(text="Risks", children=[Node(text="Flet performance")]),
        ],
    )
    assert body.write(root) == (
        "- Project\n  - Goals\n    - I/O\n    - TODO\n    - TODO\n  - Risks\n    - Flet performance\n"
    )


def test_write_includes_folded_branches() -> None:
    """Folding hides a branch from view; it is still part of the map, and still written."""
    root = Node(text="Project", children=[Node(text="Goals", folded=True, children=[Node(text="I/O")])])
    assert body.write(root) == "- Project\n  - Goals\n    - I/O\n"


def test_a_written_body_never_holds_a_fence_line() -> None:
    """Even a node whose text is a fence line is written after `- `, so the result can
    always be rendered into an `.ink` file."""
    root = Node(text="===== ink:body", children=[Node(text="===== ink:meta")])
    written = body.write(root)
    assert all(ink.section_name(line) is None for line in written.splitlines())
    assert ink.render({}, written, {"nodes": ""})  # does not raise
