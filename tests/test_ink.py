"""Tests for the `.ink` file grammar: how its sections are read and written, and what
`check` reports.

Adapted from inkspire-api's own tests of the same grammar
(https://github.com/InkSpireEditor/inkspire-api, `tests/test_ink.py`, commit `01bc14a`),
with jiyuu's section names, jiyuu's placeholder text, and without the tests of what jiyuu
does not copy (inkspire's own header fields and sections).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from jiyuu.formats import ink

META = ink.fence_line(ink.SECTION_META)
BODY = ink.fence_line(ink.SECTION_BODY)
NODES = ink.fence_line(ink.SECTION_NODES)


# --- what is a fence line --------------------------------------------------


def test_a_fence_line_names_its_section() -> None:
    """A well-formed fence line yields the name it opens."""
    assert ink.section_name("===== ink:body\n") == "body"


@pytest.mark.parametrize(
    "line",
    [
        "==== ink:body\n",
        "====== ink:body\n",
        "======ink:body\n",
        "=====ink:body\n",
        "=====\tink:body\n",
        " ===== ink:body\n",
        "===== body\n",
        "===== ink:\n",
        "===== ink:Body\n",
        "===== ink:bo-dy\n",
        "===== ink:body extra\n",
        "===== ink:body\t\n",
        "- Project\n",
        "---\n",
    ],
)
def test_a_line_that_is_not_a_fence_is_text(line: str) -> None:
    """Exactly five `=`, one space, `ink:`, a lowercase name, then nothing but spaces."""
    assert ink.section_name(line) is None


def test_trailing_spaces_on_a_fence_are_allowed() -> None:
    """Spaces after the name, and more than one before `ink:`, are still a fence."""
    assert ink.section_name("=====   ink:body   \n") == "body"


def test_a_name_may_be_thirty_two_characters_and_no_more() -> None:
    """32 characters is the longest name a fence may open."""
    assert ink.section_name(f"===== ink:{'a' * 32}\n") == "a" * 32
    assert ink.section_name(f"===== ink:{'a' * 33}\n") is None


def test_an_underscore_is_part_of_a_name() -> None:
    """Underscores are allowed in a section name."""
    assert ink.section_name("===== ink:my_own_section\n") == "my_own_section"


def test_a_fence_line_needs_no_newline_at_the_end_of_a_file() -> None:
    """The last line of a file can be a fence even with no newline after it."""
    assert ink.section_name("===== ink:body") == "body"


# --- a file with no sections -----------------------------------------------


def test_text_alone_is_all_body() -> None:
    """A file with no fence anywhere is all body, with no metadata."""
    document = ink.parse("- Project\n")
    assert document == ink.Document(metadata={}, body="- Project\n", sections={})


def test_a_markdown_rule_is_text() -> None:
    """`---` means nothing to this grammar: it is an ordinary line."""
    text = "- Project\n\n---\n\n- Goals\n"
    assert ink.parse(text) == ink.Document(metadata={}, body=text, sections={})


def test_an_empty_file_is_an_empty_body() -> None:
    """An empty file parses to an empty body."""
    assert ink.parse("") == ink.Document(metadata={}, body="", sections={})


def test_text_above_the_first_fence_leaves_the_whole_file_as_body() -> None:
    """Nothing is lost: everything in the file is still there, unparsed."""
    text = f"- Project\n{BODY}- Goals\n"
    assert ink.parse(text) == ink.Document(metadata={}, body=text, sections={})


# --- a header --------------------------------------------------------------


def test_a_header_is_read_and_the_body_kept() -> None:
    """A `meta` section's mapping and the body after it are both read."""
    document = ink.parse(f"{META}kind: mindmap\n{BODY}- Project\n")
    assert document.metadata == {"kind": "mindmap"}
    assert document.body == "- Project\n"


def test_an_empty_meta_section_is_a_header_with_nothing_in_it() -> None:
    """An empty `meta` section is no metadata, not an error."""
    assert ink.parse(f"{META}{BODY}- Project\n") == ink.Document(body="- Project\n")


def test_no_section_is_required() -> None:
    """A body without a header, and a header without a body, both parse."""
    assert ink.parse(f"{BODY}- Project\n").body == "- Project\n"
    assert ink.parse(f"{META}kind: mindmap\n").metadata == {"kind": "mindmap"}
    assert ink.parse(f"{META}kind: mindmap\n").body == ""


def test_a_body_section_may_hold_what_looks_like_front_matter() -> None:
    """`---`-fenced YAML inside the body is body text, not a header."""
    document = ink.parse(f"{BODY}---\nkind: not a header\n---\n- Project\n")
    assert document.metadata == {}
    assert document.body == "---\nkind: not a header\n---\n- Project\n"


def test_windows_line_endings_are_read_and_kept() -> None:
    """CRLF line endings are kept inside the body, byte for byte."""
    document = ink.parse(f"{META}kind: mindmap\r\n{BODY}- Project\r\n  - Goals\r\n")
    assert document.metadata == {"kind": "mindmap"}
    assert document.body == "- Project\r\n  - Goals\r\n"


def test_a_header_key_may_hold_several_lines() -> None:
    """A YAML block scalar in the header reads as one multi-line value."""
    document = ink.parse(f"{META}title: |\n  First line\n  second line\n{BODY}- Project\n")
    assert document.metadata == {"title": "First line\nsecond line\n"}


def test_accents_and_japanese_survive_a_header() -> None:
    """Non-ASCII text in the header reads back unchanged."""
    document = ink.parse(f"{META}title: Résumé, 日本語\n{BODY}- Project\n")
    assert document.metadata == {"title": "Résumé, 日本語"}


# --- a header that cannot be read ------------------------------------------


def test_a_header_that_is_not_yaml_keeps_the_body() -> None:
    """The fences say where the body is, so a broken header does not swallow it."""
    document = ink.parse(f"{META}title: [unclosed\n{BODY}- Project\n")
    assert document == ink.Document(metadata={}, body="- Project\n", sections={})


def test_a_header_that_is_a_list_keeps_the_body() -> None:
    """A header that is YAML but not a mapping costs the metadata only."""
    document = ink.parse(f"{META}- one\n- two\n{BODY}- Project\n")
    assert document == ink.Document(metadata={}, body="- Project\n", sections={})


# --- other sections --------------------------------------------------------


def test_a_nodes_section_is_carried_as_text() -> None:
    """`ink:nodes` is not interpreted here: it comes back as its own text."""
    document = ink.parse(f'{BODY}- Project\n{NODES}"7be48fc73f0ebe9c": {{side: "right"}}\n')
    assert document.body == "- Project\n"
    assert document.sections == {"nodes": '"7be48fc73f0ebe9c": {side: "right"}\n'}


def test_a_section_this_grammar_does_not_know_survives_a_round_trip() -> None:
    """A section written by something newer, or by another tool, is never deleted."""
    text = f"{BODY}- Project\n===== ink:outline\nsomething new\n"
    document = ink.parse(text)
    assert document.sections == {"outline": "something new\n"}
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_sections_keep_the_order_they_were_read_in() -> None:
    """Other sections are written back in the order they were read."""
    text = f"{BODY}- Project\n{NODES}h: x\n===== ink:outline\nx\n"
    document = ink.parse(text)
    assert list(document.sections) == ["nodes", "outline"]
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_a_section_opened_twice_keeps_its_last_occurrence() -> None:
    """As a YAML mapping would, the later of two same-named sections wins."""
    document = ink.parse(f"{BODY}- First\n{BODY}- Second\n")
    assert document.body == "- Second\n"


# --- writing one back ------------------------------------------------------


def test_a_file_is_written_back_exactly_as_it_was_read() -> None:
    """A file with a header, a body and another section round-trips byte for byte."""
    text = (
        f"{META}kind: mindmap\ntitle: |\n  Two\n  lines.\nowner: Jane Doe\n"
        f"{BODY}- Project — ünïcode, 日本語\n"
        f'{NODES}"7be48fc73f0ebe9c": {{side: "right"}}\n'
    )
    document = ink.parse(text)
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_a_body_with_no_closing_newline_is_written_back_as_it_was() -> None:
    """Nothing follows the body, so its missing final newline is not added."""
    text = f"{META}kind: mindmap\n{BODY}- Project"
    document = ink.parse(text)
    assert document.body == "- Project"
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_a_body_with_no_closing_newline_is_given_one_when_a_section_follows() -> None:
    """A fence has to start a line. This is the only byte a round trip can change."""
    rendered = ink.render({}, "- Project", {"nodes": "h: x\n"})
    assert rendered == f"{BODY}- Project\n{NODES}h: x\n"
    assert ink.parse(rendered).body == "- Project\n"
    assert ink.render({}, "- Project\n", {"nodes": "h: x\n"}) == rendered


def test_nothing_to_record_either_side_writes_no_fences() -> None:
    """A body alone is written as plain text."""
    assert ink.render({}, "- Project\n", {}) == "- Project\n"


def test_a_section_with_no_header_still_fences_the_body() -> None:
    """Another section needs the body fenced, even without a header."""
    assert ink.render({}, "- Project\n", {"nodes": "h: x\n"}) == f"{BODY}- Project\n{NODES}h: x\n"


def test_a_key_this_module_does_not_know_is_kept() -> None:
    """A header key nothing reads survives a round trip."""
    text = f"{META}kind: mindmap\nowner: Jane Doe\n{BODY}- Project\n"
    document = ink.parse(text)
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_keys_are_written_in_the_order_they_were_given() -> None:
    """Header keys keep their insertion order."""
    rendered = ink.render({"kind": "mindmap", "title": "Project"}, "", {})
    assert rendered == f"{META}kind: mindmap\ntitle: Project\n{BODY}"


def test_a_body_holding_a_fence_line_refuses_to_be_written() -> None:
    """Rather than escaping it and changing the body."""
    with pytest.raises(ValueError, match="reads as a section fence"):
        ink.render({"kind": "mindmap"}, f"- Project\n{BODY}- Goals\n", {})


def test_a_body_holding_something_that_only_looks_like_a_fence_is_fine() -> None:
    """Six `=` is not a fence, so it is ordinary body text."""
    assert ink.render({}, "====== ink:body\n", {}) == "====== ink:body\n"


# --- reading only the header -----------------------------------------------


def test_a_header_is_read_without_the_body_under_it(tmp_path: Path) -> None:
    """`read_header` reads the `meta` section of a file far longer than its budget."""
    path = tmp_path / "map.ink"
    path.write_text(f"{META}kind: mindmap\n{BODY}" + "x" * 100_000, encoding="utf-8")
    assert ink.read_header(path) == {"kind": "mindmap"}


def test_a_file_with_no_header_reads_as_no_metadata(tmp_path: Path) -> None:
    """No `meta` section, no metadata."""
    path = tmp_path / "map.ink"
    path.write_text("- Project\n", encoding="utf-8")
    assert ink.read_header(path) == {}


def test_a_header_longer_than_the_budget_is_not_read(tmp_path: Path) -> None:
    """The read stopped at the budget with no section after `meta`, so it was cut off."""
    path = tmp_path / "map.ink"
    path.write_text(f"{META}" + "x: y\n" * 50_000 + f"{BODY}- Project\n", encoding="utf-8")
    assert ink.read_header(path) == {}


def test_a_file_that_is_only_a_header_is_read(tmp_path: Path) -> None:
    """Short enough that the read reached the end of the file, so nothing was cut off."""
    path = tmp_path / "map.ink"
    path.write_text(f"{META}kind: mindmap\n", encoding="utf-8")
    assert ink.read_header(path) == {"kind": "mindmap"}


def test_a_header_below_the_first_section_is_not_read(tmp_path: Path) -> None:
    """Which is the whole reason `render` writes it first."""
    path = tmp_path / "map.ink"
    path.write_text(f"{BODY}- Project\n{META}kind: mindmap\n", encoding="utf-8")
    assert ink.read_header(path) == {}


def test_a_file_that_is_not_utf8_reads_as_no_metadata(tmp_path: Path) -> None:
    """Bytes that do not decode as UTF-8 give no metadata, not an exception."""
    path = tmp_path / "map.ink"
    path.write_bytes(META.encode("utf-8") + b"title: \xff\xfe\n")
    assert ink.read_header(path) == {}


def test_a_file_that_is_not_there_reads_as_no_metadata(tmp_path: Path) -> None:
    """A missing file gives no metadata, not an exception."""
    assert ink.read_header(tmp_path / "gone.ink") == {}


# --- check -----------------------------------------------------------------


def test_text_alone_has_nothing_to_report() -> None:
    """A file with no sections is all body, and the body is not examined."""
    assert ink.check("- Project\n") == []
    assert ink.check("") == []
    assert ink.check("- Project\n\n---\n\n- Goals\n") == []


def test_a_good_file_has_nothing_to_report() -> None:
    """A header, a body and a `nodes` section: nothing wrong."""
    text = f"{META}kind: mindmap\ntitle: Project\n{BODY}- Project\n{NODES}h: x\n"
    assert ink.check(text) == []


def test_an_unknown_header_key_is_not_reported_here() -> None:
    """What a header's keys mean is left to whatever reads them, not to the grammar."""
    assert ink.check(f"{META}owner: Jane Doe\nstatus: 3\n{BODY}- Project\n") == []


def test_an_empty_meta_section_has_nothing_to_report() -> None:
    """An empty header is fine."""
    assert ink.check(f"{META}{BODY}- Project\n") == []


def test_text_above_the_first_section_is_an_error_on_the_first_line() -> None:
    """A file that would have read as all body because of it is reported."""
    problems = ink.check(f"- Project\n{BODY}- Goals\n")
    assert [(p.line, p.level) for p in problems] == [(1, ink.ERROR)]
    assert "above its first section" in problems[0].message


def test_a_header_that_is_not_yaml_is_an_error_where_yaml_says() -> None:
    """Unparseable YAML in the header is an error."""
    problems = ink.check(f"{META}title: [unclosed\n{BODY}- Project\n")
    assert [p.level for p in problems] == [ink.ERROR]
    assert "not valid YAML" in problems[0].message


def test_a_header_that_is_not_a_mapping_is_an_error() -> None:
    """A header that is a list is an error on its first line."""
    problems = ink.check(f"{META}- one\n{BODY}- Project\n")
    assert [(p.line, p.level) for p in problems] == [(2, ink.ERROR)]
    assert "mapping" in problems[0].message


def test_an_unknown_section_is_a_warning_on_its_fence() -> None:
    """A section jiyuu gives no meaning to is a warning on its fence line."""
    problems = ink.check(f"{BODY}- Project\n===== ink:outline\nx\n")
    assert [(p.line, p.level) for p in problems] == [(3, ink.WARNING)]
    assert '"outline"' in problems[0].message


def test_a_section_opened_twice_is_an_error_on_the_second_fence() -> None:
    """The second fence of a repeated section is the one reported."""
    problems = ink.check(f"{BODY}- First\n{BODY}- Second\n")
    assert [(p.line, p.level) for p in problems] == [(3, ink.ERROR)]
    assert "more than once" in problems[0].message


def test_a_header_below_the_first_section_is_an_error() -> None:
    """A `meta` section anywhere but first is an error on its fence."""
    problems = ink.check(f"{BODY}- Project\n{META}kind: mindmap\n")
    assert [(p.line, p.level) for p in problems] == [(3, ink.ERROR)]
    assert "come first" in problems[0].message


def test_every_problem_is_reported_in_line_order() -> None:
    """Problems come out sorted by line."""
    problems = ink.check(f"{BODY}- First\n===== ink:outline\nx\n{BODY}- Second\n")
    assert [(p.line, p.level) for p in problems] == [(3, ink.WARNING), (5, ink.ERROR)]


INK_FIXTURES = sorted((Path(__file__).parent / "data" / "ink").glob("*.ink"))


@pytest.mark.parametrize("path", INK_FIXTURES, ids=lambda path: path.name)
def test_every_fixture_file_round_trips_byte_for_byte(path: Path) -> None:
    """Every `.ink` fixture reads and writes back to exactly the bytes it started as."""
    text = path.read_text(encoding="utf-8")
    document = ink.parse(text)
    assert ink.render(document.metadata, document.body, document.sections) == text


def test_there_are_fixture_files_to_round_trip() -> None:
    """The round-trip test above is only worth something if it has files to run on."""
    assert len(INK_FIXTURES) >= 3
