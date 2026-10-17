"""Tests for jiyuu's FreeMind/Freeplane `.mm` reader."""

from pathlib import Path

from jiyuu.formats.mm import read
from jiyuu.model import Node

FIXTURES = Path(__file__).parent / "data" / "mm"

BILLION_LAUGHS = """<?xml version="1.0"?>
<!DOCTYPE lolz [
 <!ENTITY lol "lol">
 <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
]>
<map><node TEXT="&lol2;"/></map>
"""


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_freemind_style_file_with_text_on_every_node() -> None:
    """A plain FreeMind file, with `TEXT` on every node and no `richcontent` at all."""
    mindmap, warnings = read(_fixture("freemind.mm"))

    assert mindmap is not None
    assert warnings == []
    assert mindmap.root.text == "Project"
    goals, risks = mindmap.root.children
    assert (goals.text, goals.side) == ("Goals", "right")
    assert (risks.text, risks.side) == ("Risks", "left")


def test_worked_example_reads_to_the_documented_tree() -> None:
    """The exact `.mm` from `ROADMAP.md`'s step 4 reads to the tree and metadata described
    there: `Goals` right and unfolded, `Risks` left, folded, and read from its rich text."""
    mindmap, warnings = read(_fixture("worked-example.mm"))

    assert mindmap is not None
    assert warnings == []
    root = mindmap.root
    assert root.text == "Project"

    goals, risks = root.children
    assert (goals.text, goals.side, goals.folded) == ("Goals", "right", False)
    assert [child.text for child in goals.children] == ["I/O"]

    assert (risks.text, risks.side, risks.folded) == ("Risks", "left", True)
    assert [child.text for child in risks.children] == ["Flet performance"]


def test_freeplane_extras_are_dropped_with_warnings_but_lose_no_node() -> None:
    """`map_styles`, `attribute_registry`, `icon`, `attribute` and a note are all dropped
    (the note specifically must never be read as the node's own text), a cloned node (no
    `TEXT`, no rich text) reads as an empty node, and every real node still comes through.
    """
    mindmap, warnings = read(_fixture("freeplane-extras.mm"))

    assert mindmap is not None
    root = mindmap.root
    assert root.text == "Project"
    goals, clone = root.children
    assert goals.text == "Goals"  # not overwritten by the <richcontent TYPE="NOTE">
    assert clone.text == ""

    joined = " ".join(warnings)
    assert "attribute_registry" in joined
    assert "map_styles" in joined
    assert "icon" in joined
    assert "attribute" in joined
    assert "clone" in joined.lower()
    # the NOTE itself is a recognised richcontent type, not an unknown dropped element
    assert "richcontent" not in joined


def test_malformed_xml_is_reported_rather_than_partially_read() -> None:
    """An unclosed tag produces a warning and `None`, never a half-built tree."""
    mindmap, warnings = read(_fixture("malformed.mm"))

    assert mindmap is None
    assert len(warnings) == 1
    assert "could not be parsed" in warnings[0]


def test_entities_and_non_ascii_text_round_trip() -> None:
    """An XML entity and a literal non-ASCII character both decode correctly."""
    mindmap, warnings = read(_fixture("entities-and-non-ascii.mm"))

    assert mindmap is not None
    assert warnings == []
    assert mindmap.root.text == "Projet & Risques"
    assert mindmap.root.children[0].text == "Résumé"


def test_a_billion_laughs_payload_is_refused_rather_than_expanded() -> None:
    """A DTD entity-expansion attack is refused, not hung on or silently expanded."""
    mindmap, warnings = read(BILLION_LAUGHS)

    assert mindmap is None
    assert len(warnings) == 1
    assert "could not be parsed" in warnings[0]


def test_no_node_at_all_under_map_is_reported() -> None:
    """A `<map>` with nothing but unrecognised children has no root to read."""
    mindmap, warnings = read('<map version="freeplane 1.9.13"><hook NAME="MapStyle"/></map>')

    assert mindmap is None
    assert any("no <node>" in warning for warning in warnings)


def test_more_than_one_top_level_node_uses_the_first_with_a_warning() -> None:
    """More than one top-level `<node>` is unusual, but the first is still read."""
    mindmap, warnings = read(
        '<map version="freeplane 1.9.13">'
        '<node TEXT="First" ID="ID_1"/>'
        '<node TEXT="Second" ID="ID_2"/>'
        "</map>"
    )

    assert mindmap is not None
    assert mindmap.root.text == "First"
    assert any("top-level" in warning for warning in warnings)


def test_rich_text_with_a_line_break_collapses_to_one_line_with_a_warning() -> None:
    """Two `<p>` paragraphs inside a node's rich text collapse to one line, one space
    between them, with a warning — unlike the single-paragraph case, which needs none."""
    mindmap, warnings = read(
        '<map version="freeplane 1.9.13">'
        "<node ID='ID_1'>"
        '<richcontent TYPE="NODE"><html><body>'
        "<p>First line</p><p>second line</p>"
        "</body></html></richcontent>"
        "</node>"
        "</map>"
    )

    assert mindmap is not None
    assert mindmap.root.text == "First line second line"
    assert any("line break" in warning for warning in warnings)


def test_a_position_value_other_than_left_or_right_is_ignored_with_a_warning() -> None:
    """An unrecognised `POSITION` value does not become a side, but is still noted."""
    mindmap, warnings = read(
        '<map version="freeplane 1.9.13">'
        '<node TEXT="Project" ID="ID_1">'
        '<node TEXT="Goals" POSITION="centre" ID="ID_2"/>'
        "</node>"
        "</map>"
    )

    assert mindmap is not None
    goals = mindmap.root.children[0]
    assert goals.side is None
    assert any("POSITION" in warning for warning in warnings)


def test_position_on_a_non_first_level_node_is_ignored_silently() -> None:
    """A `POSITION` on a node deeper than the root's own children means nothing, and is
    not even worth a warning — Freeplane itself never writes one there."""
    mindmap, warnings = read(
        '<map version="freeplane 1.9.13">'
        '<node TEXT="Project" ID="ID_1">'
        '<node TEXT="Goals" POSITION="right" ID="ID_2">'
        '<node TEXT="I/O" POSITION="right" ID="ID_3"/>'
        "</node>"
        "</node>"
        "</map>"
    )

    assert mindmap is not None
    grandchild = mindmap.root.children[0].children[0]
    assert isinstance(grandchild, Node)
    assert grandchild.side is None
    assert warnings == []
