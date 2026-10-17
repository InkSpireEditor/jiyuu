"""Tests for reading and writing a map's tree as an `.ink` body."""

import json
import random
from pathlib import Path

import pytest

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


BODIES_FIXTURE = Path(__file__).parent / "data" / "bodies.json"


def _bodies() -> list[dict]:
    return json.loads(BODIES_FIXTURE.read_text(encoding="utf-8"))


def _as_dict(node: Node) -> dict:
    """`node`'s text and children, as the plain structure `bodies.json` uses."""
    return {"text": node.text, "children": [_as_dict(child) for child in node.children]}


def _random_tree(random_source: random.Random, node_count: int) -> Node:
    """A tree of `node_count` nodes, with texts drawn from a short list so that same-text
    siblings occur, and some empty texts."""
    texts = ["Goals", "TODO", "TODO", "Risks", "", "Résumé", "A/B"]
    root = Node(text="Project")
    nodes = [root]
    for _ in range(1, node_count):
        child = Node(text=random_source.choice(texts))
        random_source.choice(nodes).children.append(child)
        nodes.append(child)
    return root


@pytest.mark.parametrize("vector", _bodies(), ids=lambda vector: vector["label"])
def test_read_matches_the_vector(vector: dict) -> None:
    """Each body reads to the tree and the problems its vector states. Problem messages are
    matched by substring, so their wording can change without breaking this."""
    root, problems = body.read(vector["body"])

    assert (None if root is None else _as_dict(root)) == vector["tree"]
    assert len(problems) == len(vector["problems"])
    for problem, expected in zip(problems, vector["problems"]):
        assert (problem.line, problem.level) == (expected["line"], expected["level"])
        assert expected["message_contains"] in problem.message


@pytest.mark.parametrize(
    "vector",
    [vector for vector in _bodies() if vector["tree"] is not None and not vector["problems"]],
    ids=lambda vector: vector["label"],
)
def test_reading_then_writing_gives_the_canonical_form(vector: dict) -> None:
    """A body already in the canonical form is written back exactly as it was; any other
    readable body is written in the canonical form, which then reads to the same tree."""
    root, _ = body.read(vector["body"])
    assert root is not None
    written = body.write(root)
    if vector["label"] == "canonical form":
        assert written == vector["body"]
    reread, problems = body.read(written)
    assert reread is not None and _as_dict(reread) == _as_dict(root)
    assert problems == []


@pytest.mark.parametrize("seed", range(10))
def test_writing_then_reading_gives_back_the_same_tree(seed: int) -> None:
    """Any tree, written and read back, is the same tree, with no problems — including
    same-text siblings and nodes with empty text."""
    tree = _random_tree(random.Random(seed), node_count=200)
    root, problems = body.read(body.write(tree))
    assert root is not None
    assert _as_dict(root) == _as_dict(tree)
    assert problems == []
