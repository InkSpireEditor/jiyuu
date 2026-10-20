"""Tests for `jiyuu.editing`: each command on a small tree, its undo and redo, and the
commands that change nothing."""

import pytest

from jiyuu.editing import UNDO_LIMIT, Editor
from jiyuu.model import Node, Task, TaskLink

Shape = tuple[str, bool, str | None, list["Shape"]]


def _tree() -> Node:
    """`Project`, with `Goals` (children `Foo`, `Bar`, `Baz`) and `Plans` on the right, and
    `Risks` (child `Qux`) on the left."""
    goals = Node(text="Goals", side="right", children=[Node(text="Foo"), Node(text="Bar"), Node(text="Baz")])
    risks = Node(text="Risks", side="left", children=[Node(text="Qux")])
    plans = Node(text="Plans", side="right")
    return Node(text="Project", children=[goals, risks, plans])


def _find(root: Node, text: str) -> Node:
    """The node of `root`'s tree with `text`, root included."""
    pending = [root]
    while pending:
        node = pending.pop()
        if node.text == text:
            return node
        pending.extend(node.children)
    raise LookupError(text)


def _shape(node: Node) -> Shape:
    """`node`'s text, folding, side and children, recursively, for comparing trees."""
    return (node.text, node.folded, node.side, [_shape(child) for child in node.children])


def _texts(node: Node) -> list[str]:
    return [child.text for child in node.children]


def test_add_child_appends_an_empty_node_and_unfolds_its_parent() -> None:
    """The new child is last, empty, returned, and shown even if its parent was folded."""
    root = _tree()
    risks = _find(root, "Risks")
    risks.folded = True
    child = Editor(root).add_child(risks)
    assert risks.children[-1] is child
    assert child.text == "" and child.side is None
    assert not risks.folded


def test_add_child_of_the_root_leaves_its_side_undecided() -> None:
    root = _tree()
    child = Editor(root).add_child(root)
    assert root.children[-1] is child and child.side is None


def test_add_sibling_inserts_right_after_the_node() -> None:
    root = _tree()
    goals = _find(root, "Goals")
    sibling = Editor(root).add_sibling(_find(root, "Foo"))
    assert goals.children[1] is sibling
    assert _texts(goals) == ["Foo", "", "Bar", "Baz"]
    assert sibling.side is None


def test_add_sibling_of_a_first_level_node_takes_its_side() -> None:
    root = _tree()
    sibling = Editor(root).add_sibling(_find(root, "Risks"))
    assert root.children[2] is sibling and sibling.side == "left"


def test_add_sibling_of_the_root_adds_a_child() -> None:
    root = _tree()
    new = Editor(root).add_sibling(root)
    assert root.children[-1] is new


@pytest.mark.parametrize(
    ("deleted", "selected"),
    [
        ("Bar", "Foo"),  # the middle of three: the previous sibling
        ("Foo", "Bar"),  # the first: the next sibling
        ("Qux", "Risks"),  # an only child: the parent
    ],
)
def test_delete_removes_the_branch_and_selects_a_neighbour(deleted: str, selected: str) -> None:
    root = _tree()
    node = _find(root, deleted)
    assert Editor(root).delete(node) is _find(root, selected)
    with pytest.raises(LookupError):
        _find(root, deleted)


def test_delete_of_a_first_level_node_selects_a_neighbour_on_its_side() -> None:
    """`Plans` comes after `Risks` in the root's children, but `Risks` is on the other side;
    the neighbour selected is `Goals`, on `Plans`'s side."""
    root = _tree()
    assert Editor(root).delete(_find(root, "Plans")) is _find(root, "Goals")
    assert _texts(root) == ["Goals", "Risks"]


def test_rename_sets_the_text_without_surrounding_whitespace() -> None:
    root = _tree()
    editor = Editor(root)
    foo = _find(root, "Foo")
    assert editor.rename(foo, "  Foo bar ") is foo
    assert foo.text == "Foo bar"
    editor.undo()
    assert foo.text == "Foo"


def test_move_up_and_move_down_swap_with_a_neighbour() -> None:
    root = _tree()
    editor = Editor(root)
    bar = _find(root, "Bar")
    assert editor.move_up(bar) is bar
    assert _texts(_find(root, "Goals")) == ["Bar", "Foo", "Baz"]
    editor.move_down(bar)
    editor.move_down(bar)
    assert _texts(_find(root, "Goals")) == ["Foo", "Baz", "Bar"]


def test_moving_a_first_level_node_swaps_it_with_its_neighbour_on_the_same_side() -> None:
    """`Plans` moves above `Goals`, over `Risks`, which is on the other side and stays put."""
    root = _tree()
    Editor(root).move_up(_find(root, "Plans"))
    assert _texts(root) == ["Plans", "Risks", "Goals"]


def test_promote_moves_a_node_next_to_its_former_parent() -> None:
    root = _tree()
    goals = _find(root, "Goals")
    goals.children[1].children.append(Node(text="Deep"))
    deep = _find(root, "Deep")
    assert Editor(root).promote(deep) is deep
    assert _texts(goals) == ["Foo", "Bar", "Deep", "Baz"]


def test_promote_to_the_first_level_takes_the_former_parents_side() -> None:
    root = _tree()
    qux = _find(root, "Qux")
    Editor(root).promote(qux)
    assert _texts(root) == ["Goals", "Risks", "Qux", "Plans"]
    assert qux.side == "left"


def test_toggle_fold_folds_and_unfolds() -> None:
    root = _tree()
    editor = Editor(root)
    goals = _find(root, "Goals")
    assert editor.toggle_fold(goals) is goals and goals.folded
    editor.toggle_fold(goals)
    assert not goals.folded


def test_set_side_moves_a_first_level_node_to_the_other_side() -> None:
    root = _tree()
    goals = _find(root, "Goals")
    assert Editor(root).set_side(goals, "left") is goals
    assert goals.side == "left"


def test_set_side_rejects_anything_but_left_or_right() -> None:
    root = _tree()
    with pytest.raises(ValueError):
        Editor(root).set_side(_find(root, "Goals"), "up")


@pytest.mark.parametrize(
    ("command", "text"),
    [
        (Editor.delete, "Project"),
        (Editor.move_up, "Foo"),
        (Editor.move_down, "Baz"),
        (Editor.move_up, "Goals"),  # first on the right side
        (Editor.move_down, "Plans"),  # last on the right side
        (Editor.move_up, "Project"),
        (Editor.promote, "Goals"),  # first-level
        (Editor.promote, "Project"),
        (Editor.toggle_fold, "Foo"),  # no children
        (lambda editor, node: editor.rename(node, " Foo "), "Foo"),  # same text once stripped
        (lambda editor, node: editor.set_side(node, "right"), "Goals"),  # already right
        (lambda editor, node: editor.set_side(node, "left"), "Foo"),  # not first-level
    ],
)
def test_a_command_that_changes_nothing_records_nothing(command, text: str) -> None:
    """The node given is returned, the tree is unchanged, and there is nothing to undo."""
    root = _tree()
    editor = Editor(root)
    before = _shape(root)
    node = _find(root, text)
    assert command(editor, node) is node
    assert _shape(root) == before
    assert editor.undo_stack == [] and editor.version == 0


def test_undo_and_redo_step_through_a_sequence_of_commands() -> None:
    """After several commands, undoing them one by one goes back through each earlier tree
    and selects the node each command was given; redoing them goes forward through each
    tree again and selects the node each command returned."""
    root = _tree()
    editor = Editor(root)
    selected = _find(root, "Bar")
    # Each command, and the text of the node it is given; `None` for the selected node.
    steps = [
        (Editor.add_child, None),
        (Editor.add_sibling, None),
        (Editor.promote, None),
        (Editor.move_up, None),
        (Editor.delete, None),
        (Editor.toggle_fold, "Goals"),
        (lambda editor, node: editor.set_side(node, "left"), "Plans"),
        (lambda editor, node: editor.rename(node, "Bar"), "Plans"),
    ]
    shapes, given, returned = [_shape(root)], [], []
    for command, text in steps:
        node = selected if text is None else _find(root, text)
        selected = command(editor, node)
        given.append(node)
        returned.append(selected)
        shapes.append(_shape(root))
        assert shapes[-1] != shapes[-2]

    for index in reversed(range(len(steps))):
        assert editor.undo() is given[index]
        assert _shape(root) == shapes[index]
    assert editor.undo() is None

    for index in range(len(steps)):
        assert editor.redo() is returned[index]
        assert _shape(root) == shapes[index + 1]
    assert editor.redo() is None


def test_undoing_a_delete_brings_back_the_same_node_objects() -> None:
    root = _tree()
    editor = Editor(root)
    goals = _find(root, "Goals")
    foo = goals.children[0]
    editor.delete(goals)
    editor.undo()
    assert root.children[0] is goals and goals.children[0] is foo


def test_a_new_command_empties_the_redo_stack() -> None:
    root = _tree()
    editor = Editor(root)
    editor.add_child(root)
    editor.undo()
    editor.toggle_fold(_find(root, "Goals"))
    assert editor.redo_stack == []
    assert editor.redo() is None


def test_the_undo_stack_keeps_only_the_latest_changes() -> None:
    root = _tree()
    editor = Editor(root)
    goals = _find(root, "Goals")
    for _ in range(UNDO_LIMIT + 5):
        editor.toggle_fold(goals)
    assert len(editor.undo_stack) == UNDO_LIMIT
    assert all(editor.undo() is goals for _ in range(UNDO_LIMIT))
    assert editor.undo() is None
    assert goals.folded  # the five oldest folds cannot be undone: 105 - 100 leaves it folded


def _link(uuid: str, text: str) -> TaskLink:
    return TaskLink(uuid=uuid, synced="20261019T211745Z", text=text, task=Task())


def test_deleting_a_branch_orphans_its_task_links_and_undo_takes_them_back() -> None:
    """Goals and Foo are synced tasks, Bar a task never synced: deleting Goals moves the two
    links to the orphaned links, after the one already there; undo restores the list."""
    root = _tree()
    goals, foo, bar = _find(root, "Goals"), _find(root, "Foo"), _find(root, "Bar")
    goals.task = foo.task = bar.task = Task()
    goals.task_link, foo.task_link = _link("1", "Goals"), _link("2", "Foo")
    orphans = [_link("0", "Old")]
    editor = Editor(root, orphans)

    editor.delete(goals)
    assert [link.uuid for link in orphans] == ["0", "1", "2"]
    editor.undo()
    assert [link.uuid for link in orphans] == ["0"]
    assert goals in root.children and goals.task_link == _link("1", "Goals")
    editor.redo()
    assert [link.uuid for link in orphans] == ["0", "1", "2"]


def test_undo_puts_back_a_task_and_its_link() -> None:
    """A node's task and link are part of what each command records."""
    root = _tree()
    foo = _find(root, "Foo")
    foo.task, foo.task_link = Task(done=True), _link("2", "Foo")
    editor = Editor(root)
    editor.rename(foo, "Food")
    foo.task, foo.task_link = None, None  # as a later command would leave them
    editor.undo()
    assert (foo.text, foo.task, foo.task_link) == ("Foo", Task(done=True), _link("2", "Foo"))
