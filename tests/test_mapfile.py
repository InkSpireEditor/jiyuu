"""Tests for reading and writing maps as `.ink` files, `ink:nodes` included."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jiyuu.formats import mapfile
from jiyuu.model import MindMap, Node, node_id

DATA = Path(__file__).parent / "data"
INK_FIXTURES = DATA / "ink"


def _fixture(name: str) -> str:
    return (INK_FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["worked-example.ink", "unknown-section.ink", "folded.ink"])
def test_read_then_dump_reproduces_the_file_byte_for_byte(name: str) -> None:
    """Every fixture that is already in the form `dump` writes comes back unchanged,
    including a section jiyuu does not know."""
    text = _fixture(name)
    mindmap, _ = mapfile.read(text)
    assert mindmap is not None
    assert mapfile.dump(mindmap) == text


def test_load_reads_a_file_from_disk(tmp_path: Path) -> None:
    """`load` is `read` on the file's text."""
    path = tmp_path / "map.ink"
    path.write_text(_fixture("worked-example.ink"), encoding="utf-8")
    mindmap, problems = mapfile.load(path)
    assert mindmap is not None and problems == []
    assert mindmap.root.text == "Project"


def test_read_applies_sides_and_folding() -> None:
    """Each node gets its own entry's side and folding; a node with no entry gets the
    defaults."""
    mindmap, problems = mapfile.read(_fixture("folded.ink"))
    assert mindmap is not None and problems == []
    goals, risks = mindmap.root.children
    assert (goals.side, goals.folded) == ("right", True)
    assert (risks.side, risks.folded) == ("left", False)
    assert goals.children[0].folded is False
    assert mindmap.other_sections == {}


def test_read_keeps_meta_and_adds_the_kind_where_missing() -> None:
    """`meta` keys are kept in order; `kind: mindmap` is added after them if absent."""
    mindmap, problems = mapfile.read("===== ink:meta\ntitle: Project\n===== ink:body\n- Project\n")
    assert mindmap is not None and problems == []
    assert list(mindmap.meta.items()) == [("title", "Project"), ("kind", "mindmap")]


def test_an_entry_matching_no_node_is_dropped_on_the_next_dump() -> None:
    """A node renamed in a text editor loses its entry: the old entry matches nothing, so
    the node gets defaults and the entry is not written again."""
    text = _fixture("folded.ink").replace("  - Goals\n", "  - Aims\n")
    mindmap, problems = mapfile.read(text)
    assert mindmap is not None and problems == []
    aims = mindmap.root.children[0]
    assert (aims.side, aims.folded) == (None, False)
    assert node_id([["Goals", 1]]) not in mapfile.dump(mindmap)


def test_an_all_digit_id_is_written_quoted_and_matches_its_node_again() -> None:
    """An id made only of decimal digits is quoted on write, and reads back as text that
    matches its node, not as an integer that matches nothing."""
    vectors = json.loads((DATA / "node_ids.json").read_text(encoding="utf-8"))
    vector = next(v for v in vectors if v["id"].isdigit())
    (_, first), (_, second) = vector["path"]
    assert first == second == 1
    child = Node(text=vector["path"][1][0], folded=True, children=[Node(text="Foo")])
    root = Node(text="Project", children=[Node(text=vector["path"][0][0], children=[child])])

    text = mapfile.dump(MindMap(root=root))
    assert f'"{vector["id"]}": {{folded: "true"}}\n' in text
    mindmap, problems = mapfile.read(text)
    assert mindmap is not None and problems == []
    assert mindmap.root.children[0].children[0].folded is True


def test_unquoted_keys_and_values_written_by_hand_still_read() -> None:
    """A key or value typed without quotes reads as the same text as a quoted one."""
    mindmap, problems = mapfile.read(
        "===== ink:body\n- Project\n  - Goals\n===== ink:nodes\n7be48fc73f0ebe9c: {side: left, folded: true}\n"
    )
    assert mindmap is not None and problems == []
    assert (mindmap.root.children[0].side, mindmap.root.children[0].folded) == ("left", True)


def test_unknown_fields_are_kept_and_written_back() -> None:
    """A field jiyuu gives no meaning to stays on its node and is written back first."""
    text = '===== ink:body\n- Project\n  - Goals\n===== ink:nodes\n"7be48fc73f0ebe9c": {colour: "red", side: "right"}\n'
    mindmap, _ = mapfile.read(text)
    assert mindmap is not None
    assert mindmap.root.children[0].extra == {"colour": "red"}
    assert mapfile.dump(mindmap).endswith('"7be48fc73f0ebe9c": {colour: "red", side: "right"}\n')


def test_a_side_on_a_deeper_node_is_not_written_back() -> None:
    """Only the root's children have a side; one given to a deeper node is not kept."""
    goals = Node(text="Goals", children=[Node(text="I/O", side="left")])
    assert mapfile.build_nodes_section(Node(text="Project", children=[goals])) == {}


def test_an_unknown_side_reads_as_undecided() -> None:
    """A `side` that is neither left nor right is treated as absent."""
    mindmap, _ = mapfile.read('===== ink:body\n- Project\n  - Goals\n===== ink:nodes\n"7be48fc73f0ebe9c": {side: "up"}\n')
    assert mindmap is not None
    assert mindmap.root.children[0].side is None


def test_a_map_with_nothing_to_record_has_no_nodes_section() -> None:
    """With no side decided and nothing folded, `dump` writes no `ink:nodes` at all."""
    text = mapfile.dump(MindMap(root=Node(text="Project", children=[Node(text="Goals")])))
    assert text == "===== ink:meta\nkind: mindmap\n===== ink:body\n- Project\n  - Goals\n"


def test_prose_with_no_fences_opens_as_a_one_node_map_with_a_warning() -> None:
    """A file with no fences and no marker reads as a root holding its one line, with a
    warning that it is not marked as a map and one that the line has no marker."""
    mindmap, problems = mapfile.read("Some notes about the project.\n")
    assert mindmap is not None
    assert mindmap.root.text == "Some notes about the project."
    assert mindmap.root.children == []
    assert [(p.line, p.level) for p in problems] == [(1, "warning"), (1, "warning")]
    assert any("kind: mindmap" in p.message for p in problems)


def test_another_kind_is_warned_about_and_kept() -> None:
    """A file marked as something other than a map is read anyway, with a warning, and
    keeps its own kind."""
    mindmap, problems = mapfile.read("===== ink:meta\nkind: note\n===== ink:body\n- Project\n")
    assert mindmap is not None
    assert mindmap.meta["kind"] == "note"
    assert [p.line for p in problems] == [1]
    assert "kind: note" in problems[0].message


def test_body_problems_are_numbered_by_line_in_the_whole_file() -> None:
    """A problem on the body's second line, in a file whose body starts on line 4, is on
    line 5."""
    _, problems = mapfile.read("===== ink:meta\nkind: mindmap\n===== ink:body\n- Project\n  Goals\n")
    assert [(p.line, p.level) for p in problems] == [(5, "warning")]


def test_a_body_opened_twice_counts_lines_from_the_last_fence() -> None:
    """The second body is the one read, so its lines are counted from its own fence; the
    repeated section is reported too."""
    _, problems = mapfile.read("===== ink:body\n- One\n===== ink:body\n- Project\n  Goals\n")
    assert [(p.line, p.level) for p in problems] == [(3, "error"), (5, "warning")]


def test_a_file_with_no_body_has_no_map() -> None:
    """Sections but no body means no tree to show."""
    mindmap, problems = mapfile.read("===== ink:meta\nkind: mindmap\n")
    assert mindmap is None
    assert "empty" in problems[0].message


@pytest.mark.parametrize(
    ("nodes", "line", "message"),
    [
        ('"a": {side: "left"\n', 6, "not valid YAML"),
        ("- a\n- b\n", 5, "not a mapping"),
        ('"7be48fc73f0ebe9c": "right"\n', 5, "not a mapping"),
        ('"7be48fc73f0ebe9c": {side: [left]}\n', 5, "not a string"),
    ],
)
def test_nodes_problems_are_reported_and_cost_only_the_metadata(nodes: str, line: int, message: str) -> None:
    """An `ink:nodes` section that cannot be used is reported on its own lines; the tree is
    still read, with defaults."""
    mindmap, problems = mapfile.read(f"===== ink:body\n- Project\n  - Goals\n===== ink:nodes\n{nodes}")
    assert mindmap is not None
    assert mindmap.root.children[0].side is None
    assert [(p.line, p.level) for p in problems] == [(line, "warning")]
    assert message in problems[0].message


def test_dump_reads_back_as_the_same_tree_and_metadata() -> None:
    """Folding, sides and same-text siblings all survive a dump and a read."""
    root = Node(
        text="Project",
        children=[
            Node(text="TODO", side="left", children=[Node(text="Foo")], folded=True),
            Node(text="TODO", side="right", children=[Node(text="Bar", folded=True, children=[Node(text="Baz")])]),
        ],
    )
    mindmap, problems = mapfile.read(mapfile.dump(MindMap(root=root)))
    assert mindmap is not None and problems == []
    first, second = mindmap.root.children
    assert (first.side, first.folded, second.side, second.folded) == ("left", True, "right", False)
    assert second.children[0].folded is True
