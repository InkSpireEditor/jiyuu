"""Tests for moving the selection around a map with the keyboard."""

import pytest

from jiyuu.model import Node
from jiyuu.navigation import DOWN, HOME, LEFT, RIGHT, UP, Navigator, is_inside


def _map() -> dict[str, Node]:
    """A map with two branches on the right and one on the left, named for lookup:

        Project
          right: Goals (I/O, TODO, Tests) , Risks
          left:  Ideas (Later (Someday))
    """
    nodes = {name: Node(text=name) for name in
             ["Project", "Goals", "I/O", "TODO", "Tests", "Risks", "Ideas", "Later", "Someday"]}
    nodes["Goals"].children = [nodes["I/O"], nodes["TODO"], nodes["Tests"]]
    nodes["Later"].children = [nodes["Someday"]]
    nodes["Ideas"].children = [nodes["Later"]]
    nodes["Goals"].side = nodes["Risks"].side = RIGHT
    nodes["Ideas"].side = LEFT
    nodes["Project"].children = [nodes["Goals"], nodes["Risks"], nodes["Ideas"]]
    return nodes


@pytest.mark.parametrize(
    ("selected", "key", "expected"),
    [
        # from the root, Right and Left go outward into each side, picking the middle child
        ("Project", RIGHT, "Risks"),  # right side has Goals, Risks: middle (index 1) is Risks
        ("Project", LEFT, "Ideas"),
        ("Project", UP, "Project"),
        # right side: Right goes to a child (the middle one), Left back to the parent
        ("Goals", RIGHT, "TODO"),
        ("Goals", LEFT, "Project"),
        ("TODO", LEFT, "Goals"),
        # left side: the reverse
        ("Ideas", LEFT, "Later"),
        ("Ideas", RIGHT, "Project"),
        ("Later", RIGHT, "Ideas"),
        # Up and Down between siblings, nothing past either end
        ("TODO", UP, "I/O"),
        ("TODO", DOWN, "Tests"),
        ("I/O", UP, "I/O"),
        ("Tests", DOWN, "Tests"),
        # the root's children move only among those on their own side
        ("Risks", DOWN, "Risks"),
        ("Goals", UP, "Goals"),
        # a leaf has nowhere outward to go
        ("Risks", RIGHT, "Risks"),
        ("Someday", LEFT, "Someday"),
        # Home from anywhere
        ("Someday", HOME, "Project"),
    ],
)
def test_move(selected: str, key: str, expected: str) -> None:
    """Each key from each kind of position selects what the rules say it should."""
    nodes = _map()
    navigator = Navigator(nodes["Project"])
    assert navigator.move(nodes[selected], key) is nodes[expected]


def test_a_folded_node_cannot_be_entered() -> None:
    """Moving outward from a folded node does nothing: its children are not shown."""
    nodes = _map()
    nodes["Goals"].folded = True
    assert Navigator(nodes["Project"]).move(nodes["Goals"], RIGHT) is nodes["Goals"]


def test_re_entering_returns_to_the_child_last_left() -> None:
    """Going back out of a subtree and in again selects where the selection came out of,
    not the middle child."""
    nodes = _map()
    navigator = Navigator(nodes["Project"])
    assert navigator.move(nodes["Tests"], LEFT) is nodes["Goals"]
    assert navigator.move(nodes["Goals"], RIGHT) is nodes["Tests"]


def test_the_root_remembers_each_side_separately() -> None:
    """Coming back to the root from the left side does not change where Right goes."""
    nodes = _map()
    navigator = Navigator(nodes["Project"])
    navigator.move(nodes["Goals"], LEFT)  # leave the right side from Goals
    navigator.move(nodes["Ideas"], RIGHT)  # leave the left side from Ideas
    assert navigator.move(nodes["Project"], RIGHT) is nodes["Goals"]
    assert navigator.move(nodes["Project"], LEFT) is nodes["Ideas"]


def test_side_of_is_the_first_level_ancestors_side() -> None:
    """A deep node is on whichever side its branch is on; the root is on neither."""
    nodes = _map()
    navigator = Navigator(nodes["Project"])
    assert navigator.side_of(nodes["Someday"]) == LEFT
    assert navigator.side_of(nodes["TODO"]) == RIGHT
    assert navigator.side_of(nodes["Project"]) is None


def test_is_inside() -> None:
    """A node is inside its ancestors, and not inside itself or a node off its branch."""
    nodes = _map()
    assert is_inside(nodes["Someday"], nodes["Ideas"])
    assert not is_inside(nodes["Ideas"], nodes["Ideas"])
    assert not is_inside(nodes["TODO"], nodes["Ideas"])


def test_a_key_that_is_not_a_move_leaves_the_selection_alone() -> None:
    """Anything other than the five moves selects nothing new."""
    nodes = _map()
    assert Navigator(nodes["Project"]).move(nodes["TODO"], "page down") is nodes["TODO"]
