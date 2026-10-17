"""Tests for jiyuu's node tree and the ids its stored metadata is keyed by."""

import json
from pathlib import Path

import pytest

from jiyuu.model import MindMap, Node, depths, descendant_count, node_id, parent_of, path_of, walk

NODE_IDS_FIXTURE = Path(__file__).parent / "data" / "node_ids.json"


def _node_id_vectors() -> list[dict]:
    return json.loads(NODE_IDS_FIXTURE.read_text(encoding="utf-8"))


@pytest.mark.parametrize("vector", _node_id_vectors(), ids=lambda vector: vector["label"])
def test_node_id_matches_the_hand_computed_vector(vector: dict) -> None:
    """`node_id` reproduces every hash in `node_ids.json` exactly, not just approximately."""
    assert node_id(vector["path"]) == vector["id"]


def test_walk_visits_every_descendant_depth_first_excluding_the_root() -> None:
    """`walk` yields every node under the root, depth-first, and never the root itself."""
    grandchild = Node(text="I/O")
    child_a = Node(text="Goals", children=[grandchild])
    child_b = Node(text="Risks")
    root = Node(text="Project", children=[child_a, child_b])

    assert list(walk(root)) == [child_a, grandchild, child_b]


def test_parent_of_the_root_is_none() -> None:
    """`parent_of` answers `None` for the root, and only for the root."""
    root = Node(text="Project")
    assert parent_of(root, root) is None


def test_parent_of_finds_a_descendants_immediate_parent() -> None:
    """`parent_of` finds a node's parent anywhere in the tree, not just at the top level."""
    grandchild = Node(text="I/O")
    child = Node(text="Goals", children=[grandchild])
    root = Node(text="Project", children=[child])

    assert parent_of(child, root) is root
    assert parent_of(grandchild, root) is child


def test_parent_of_a_node_outside_the_tree_raises() -> None:
    """A node that is not `root` and not reachable from it is an error, not `None`."""
    root = Node(text="Project")
    stray = Node(text="Nowhere")

    with pytest.raises(ValueError):
        parent_of(stray, root)


def test_occurrence_is_positional_among_identical_same_text_siblings() -> None:
    """Two structurally identical same-text siblings still get different occurrences.

    Both `TODO` nodes here are bare leaves with no field that tells them apart, which is
    exactly the case the `node_ids.json` "first/second same-text sibling" vectors cover:
    the only thing that distinguishes them is their position among `Goals`'s children, so
    reordering that position has to move which one is "first" with it.
    """
    first_todo = Node(text="TODO")
    second_todo = Node(text="TODO")
    goals = Node(text="Goals", children=[first_todo, second_todo])
    root = Node(text="Project", children=[goals])

    assert path_of(first_todo, root) == [["Goals", 1], ["TODO", 1]]
    assert path_of(second_todo, root) == [["Goals", 1], ["TODO", 2]]

    goals.children.reverse()

    assert path_of(second_todo, root) == [["Goals", 1], ["TODO", 1]]
    assert path_of(first_todo, root) == [["Goals", 1], ["TODO", 2]]


def test_path_of_the_root_is_empty() -> None:
    """The root is never part of its own path."""
    root = Node(text="Project")
    assert path_of(root, root) == []


def test_mindmap_defaults_to_empty_metadata() -> None:
    """A `MindMap` given only a root starts with no header fields and no other sections."""
    mindmap = MindMap(root=Node(text="Project"))
    assert mindmap.meta == {}
    assert mindmap.other_sections == {}


def test_depths_counts_distance_from_the_root_folded_or_not() -> None:
    """The root is at depth 0, its children at 1, and a folded node's children still count."""
    grandchild = Node(text="I/O")
    child = Node(text="Goals", folded=True, children=[grandchild])
    root = Node(text="Project", children=[child])

    assert depths(root) == {root: 0, child: 1, grandchild: 2}


def test_descendant_count_counts_every_level_but_not_the_node_itself() -> None:
    """Two children, one of which has a child of its own: three descendants."""
    node = Node(text="Goals", children=[Node(text="I/O", children=[Node(text="Sockets")]), Node(text="TODO")])

    assert descendant_count(node) == 3
    assert descendant_count(Node(text="leaf")) == 0
