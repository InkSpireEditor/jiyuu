"""Tests for jiyuu's layout algorithm."""

import random

from jiyuu.layout import LayoutSettings, Rect, layout, subtree_height
from jiyuu.measure import FixedMeasurer
from jiyuu.model import Node

MEASURER = FixedMeasurer(width_per_char=10.0, height=16.0)
SETTINGS = LayoutSettings()  # pad_x=16, pad_y=8, vertical_gap=12, horizontal_gap=48


def _random_tree(random_source: random.Random, node_count: int) -> Node:
    """A tree of exactly `node_count` nodes (the root plus `node_count - 1` descendants),
    each attached under a uniformly-chosen existing node, with short, cheap-to-measure text.
    """
    root = Node(text="n0")
    nodes = [root]
    for i in range(1, node_count):
        parent = random_source.choice(nodes)
        child = Node(text=f"n{i}")
        parent.children.append(child)
        nodes.append(child)
    return root


def _overlap(first: Rect, second: Rect) -> bool:
    """Whether `first` and `second` share any area at all."""
    return (
        first.x < second.x + second.width
        and second.x < first.x + first.width
        and first.y < second.y + second.height
        and second.y < first.y + first.height
    )


def test_single_root_with_no_children() -> None:
    """A lone root is centred on the origin, with no edges."""
    root = Node(text="Project")
    rects, edges = layout(root, MEASURER, SETTINGS)

    width, height = 7 * 10.0 + 2 * 16.0, 16.0 + 2 * 8.0  # 102, 32
    assert rects == {root: Rect(-width / 2, -height / 2, width, height)}
    assert edges == []


def test_one_child_on_each_side() -> None:
    """Two equal-height children, explicitly sided, land as mirror images of each other."""
    right_child = Node(text="Goals", side="right")
    left_child = Node(text="Risks", side="left")
    root = Node(text="Project", children=[right_child, left_child])

    rects, edges = layout(root, MEASURER, SETTINGS)

    root_width, root_height = 7 * 10.0 + 32.0, 32.0  # 102, 32
    child_width, child_height = 5 * 10.0 + 32.0, 32.0  # 82, 32
    root_rect = Rect(-root_width / 2, -root_height / 2, root_width, root_height)
    assert rects[root] == root_rect

    right_x = root_rect.x + root_rect.width + SETTINGS.horizontal_gap
    left_x = root_rect.x - SETTINGS.horizontal_gap - child_width
    assert rects[right_child] == Rect(right_x, -child_height / 2, child_width, child_height)
    assert rects[left_child] == Rect(left_x, -child_height / 2, child_width, child_height)

    assert {(edge.child, edge.side) for edge in edges} == {
        (right_child, "right"),
        (left_child, "left"),
    }


def test_balancing_alternates_sides_for_equal_height_children_with_no_side_set() -> None:
    """With nobody's side set by hand, three equal-height children alternate: right, left,
    right — ties, including the first child against two empty columns, go to the right."""
    children = [Node(text="a"), Node(text="b"), Node(text="c")]
    root = Node(text="Project", children=children)

    layout(root, MEASURER, SETTINGS)

    assert [child.side for child in children] == ["right", "left", "right"]


def test_an_explicit_side_is_kept_even_if_it_unbalances_the_columns() -> None:
    """A child's own side is never overridden by the balancing rule, however lopsided the
    result, and it still counts toward its side's running height for the next child."""
    heavy = Node(text="a very much longer piece of text than the other one", side="left")
    light = Node(text="b")  # no side: must balance against `heavy`'s real height, not 0
    root = Node(text="Project", children=[heavy, light])

    layout(root, MEASURER, SETTINGS)

    assert heavy.side == "left"
    assert light.side == "right"  # left is now far heavier, so light goes right


def test_a_folded_nodes_subtree_takes_only_its_own_height() -> None:
    """Folding a node drops its descendants from the layout entirely, not just from view."""
    grandchildren = [Node(text=f"g{i}") for i in range(5)]
    folded = Node(text="Folded", folded=True, children=grandchildren, side="right")
    root = Node(text="Project", children=[folded])

    _, own_height = 16.0 + 2 * 8.0, 16.0 + 2 * 8.0
    assert subtree_height(folded, MEASURER, SETTINGS) == own_height

    rects, edges = layout(root, MEASURER, SETTINGS)
    assert folded in rects
    assert all(grandchild not in rects for grandchild in grandchildren)
    assert all(edge.child is not g for edge in edges for g in grandchildren)


def test_no_two_boxes_overlap_across_many_random_trees() -> None:
    """Across a range of random tree shapes up to 200 nodes, no two boxes ever overlap."""
    for seed in range(20):
        tree = _random_tree(random.Random(seed), node_count=200)
        rects, _ = layout(tree, MEASURER, SETTINGS)
        boxes = list(rects.values())
        for i, first in enumerate(boxes):
            for second in boxes[i + 1 :]:
                assert not _overlap(first, second), f"seed {seed}: {first} overlaps {second}"


def test_every_edge_touches_its_two_boxes_facing_edges_across_random_trees() -> None:
    """An edge's child sits exactly `horizontal_gap` beyond its parent's facing edge, on
    whichever side the edge says — the gap this layout promises, not merely close to it."""
    for seed in range(20):
        tree = _random_tree(random.Random(seed), node_count=200)
        rects, edges = layout(tree, MEASURER, SETTINGS)
        for edge in edges:
            parent_rect, child_rect = rects[edge.parent], rects[edge.child]
            if edge.side == "right":
                assert child_rect.x == parent_rect.x + parent_rect.width + SETTINGS.horizontal_gap
            else:
                assert child_rect.x + child_rect.width == parent_rect.x - SETTINGS.horizontal_gap
