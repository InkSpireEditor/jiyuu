"""Tests for reading and writing a map's tree as an `.ink` body."""

import json
import random
from pathlib import Path

import pytest

from jiyuu.formats import body, ink
from jiyuu.model import Node, Task


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
    """`node`'s text and children, as the plain structure `bodies.json` uses, and its task
    if it has one."""
    shape: dict = {"text": node.text, "children": [_as_dict(child) for child in node.children]}
    if node.task is not None:
        shape["task"] = node.task
    return shape


def _random_tree(random_source: random.Random, node_count: int) -> Node:
    """A tree of `node_count` nodes, with texts drawn from a short list so that same-text
    siblings occur, and some empty texts, texts that need escaping, and tasks."""
    texts = ["Goals", "TODO", "TODO", "Risks", "", "Résumé", "A/B", "[ ] Foo", "\\Bar", "Baz due:x", "priority:H"]
    tasks = [None, None, Task(), Task(done=True), Task(due="2026-10-25"), Task(due="2026-10-25T14:00", priority="L")]
    root = Node(text="Project")
    nodes = [root]
    for _ in range(1, node_count):
        child = Node(text=random_source.choice(texts), task=random_source.choice(tasks))
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
    same-text siblings, nodes with empty text, text that needs escaping, and tasks."""
    tree = _random_tree(random.Random(seed), node_count=200)
    root, problems = body.read(body.write(tree))
    assert root is not None
    assert _as_dict(root) == _as_dict(tree)
    assert problems == []


def _task_line(content: str) -> tuple[Node, list[ink.Problem]]:
    """The node read from a body whose root has one child, written `- <content>`."""
    root, problems = body.read(f"- Project\n  - {content}\n")
    assert root is not None
    return root.children[0], problems


@pytest.mark.parametrize(
    ("content", "text", "task"),
    [
        ("[ ] Foo", "Foo", Task()),
        ("[x] Foo", "Foo", Task(done=True)),
        ("[X] Foo", "Foo", Task(done=True)),
        ("[ ] Foo  due:2026-10-25 priority:H", "Foo", Task(due="2026-10-25", priority="H")),
        ("[ ] Foo priority:L due:2026-10-25T14:00", "Foo", Task(due="2026-10-25T14:00", priority="L")),
        ("[ ]", "", Task()),
        ("[ ]  due:2026-10-25", "", Task(due="2026-10-25")),
        ("[ ] Foo  Bar", "Foo  Bar", Task()),
        ("[ ] Foo due\\:soon", "Foo due:soon", Task()),
        ("[ ] due:2026-10-25 Foo", "due:2026-10-25 Foo", Task()),
    ],
    ids=[
        "pending", "done", "capital x", "fields", "fields in either order", "no text",
        "no text with a field", "two spaces in the text", "escaped field", "field before text",
    ],
)
def test_a_checkbox_makes_a_task_and_its_trailing_fields_are_read(content: str, text: str, task: Task) -> None:
    node, problems = _task_line(content)
    assert (node.text, node.task, problems) == (text, task, [])


@pytest.mark.parametrize(
    ("content", "text", "task", "message"),
    [
        ("[ ] Foo due:soon", "Foo due:soon", Task(), "not a date"),
        ("[ ] Foo due:2026-02-30", "Foo due:2026-02-30", Task(), "not a date"),
        ("[ ] Foo priority:X", "Foo priority:X", Task(), "not one of H, M, L"),
        ("[ ] Foo due:2026-10-24 due:2026-10-25", "Foo due:2026-10-24", Task(due="2026-10-25"), "given twice"),
    ],
    ids=["not a date", "no such day", "unknown priority", "field twice"],
)
def test_an_invalid_field_is_reported_and_read_as_text(content: str, text: str, task: Task, message: str) -> None:
    node, problems = _task_line(content)
    assert (node.text, node.task) == (text, task)
    assert [(p.line, p.level) for p in problems] == [(2, ink.WARNING)] and message in problems[0].message


@pytest.mark.parametrize("content", ["[]Foo", "[x]Foo", "[ ]Foo", "Foo [ ]"])
def test_text_that_only_looks_like_a_checkbox_is_plain(content: str) -> None:
    node, problems = _task_line(content)
    assert (node.text, node.task, problems) == (content, None, [])


def test_the_root_cannot_be_a_task() -> None:
    root, problems = body.read("- [ ] Project\n")
    assert root is not None and root.text == "[ ] Project" and root.task is None
    assert [(p.line, p.level) for p in problems] == [(1, ink.WARNING)]
    assert body.write(root) == "- \\[ ] Project\n"


def test_write_puts_the_checkbox_then_the_text_then_the_fields() -> None:
    root = Node(
        text="Project",
        children=[
            Node(text="Foo", task=Task(due="2026-10-25", priority="H")),
            Node(text="Bar", task=Task(done=True)),
            Node(text="", task=Task(priority="M")),
            Node(text="", task=Task()),
        ],
    )
    assert body.write(root) == (
        "- Project\n  - [ ] Foo  due:2026-10-25 priority:H\n  - [x] Bar\n  - [ ]  priority:M\n  - [ ]\n"
    )


@pytest.mark.parametrize(
    ("text", "task", "content"),
    [
        ("[ ] not a task", None, "\\[ ] not a task"),
        ("[x]", None, "\\[x]"),
        ("\\back", None, "\\\\back"),
        ("[x]y", None, "[x]y"),
        ("Foo due:soon", Task(), "[ ] Foo due\\:soon"),
        ("Foo due\\:soon priority:x", Task(due="2026-10-25"), "[ ] Foo due\\\\:soon priority\\:x  due:2026-10-25"),
        ("due:x Foo", Task(), "[ ] due:x Foo"),
        ("[ ] Foo", Task(), "[ ] [ ] Foo"),
        ("\\Foo", Task(), "[ ] \\Foo"),
    ],
)
def test_text_that_would_read_differently_is_escaped_and_reads_back(text: str, task: Task | None, content: str) -> None:
    root = Node(text="Project", children=[Node(text=text, task=task)])
    written = body.write(root)
    assert written == f"- Project\n  - {content}\n"
    read, problems = body.read(written)
    assert read is not None and problems == []
    assert (read.children[0].text, read.children[0].task) == (text, task)


@pytest.mark.parametrize(
    ("value", "valid"),
    [("2026-10-25", True), ("2026-10-25T14:00", True), ("2026-10-25T14:00:00", False), ("2026-13-01", False),
     ("2026-10-25T25:00", False), ("tomorrow", False), ("20261025", False)],
)
def test_is_due_date(value: str, valid: bool) -> None:
    assert body.is_due_date(value) is valid
