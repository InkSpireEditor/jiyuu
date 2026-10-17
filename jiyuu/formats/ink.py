"""The `.ink` file grammar: a sequence of named sections, one of which is the body.

A file is a sequence of sections. Each opens with a fence line naming it, and runs to the
next fence line or to the end of the file:

    ===== ink:meta
    kind: mindmap
    ===== ink:body
    - Project
      - Goals
    ===== ink:nodes
    "7be48fc73f0ebe9c": {side: "right"}

A fence line is exactly five `=`, at least one space, `ink:`, a name of 1 to 32 lowercase
ASCII letters and underscores, and then nothing but spaces before the end of the line. A
line that differs in any way — four or six `=`, a tab, an uppercase letter — is an ordinary
line of text. As a grammar, lines classified first and then parsed:

    fence-line = "=====" 1*SP "ink:" name *SP EOL
    name       = 1*32( %x61-7A / "_" )        ; lowercase ASCII and underscore
    text-line  = *( %x00-09 / %x0B-FF ) EOL   ; any line that is not a fence-line
    EOL        = LF / CRLF

    file     = bare / *section
    bare     = *text-line                     ; no fence anywhere: the whole file is body
    section  = fence-line *text-line

`ink:meta`, when present, comes first and is a YAML mapping; `ink:body` is the file's main
text, which this module does not interpret; every other section is carried as text,
unread. A file with no fence line anywhere is all body. A file with text above its first
fence is read as all body too, so that no text is ever lost to a parse it did not fit.

Reading is forgiving: a `meta` section that is not YAML, or not a mapping, costs only the
metadata, never the body, and a section named twice keeps its last occurrence. `check` is
where those problems are reported instead. Writing (`render`) is exact: a file read and
written back is byte-identical, with one exception — a section followed by another is given
a closing newline if it has none, since a fence has to start a line — and unknown sections
and unknown `meta` keys are kept as they were, in the order they were read.

This grammar is the one inkspire-api uses for its own `.ink` files
(https://github.com/InkSpireEditor/inkspire-api, `inkspire_api/ink.py` and
`docs/ink-format.md`, commit `01bc14a`), copied rather than shared as a dependency. It
differs from that file only where noted here: the section names it knows are jiyuu's own
(`meta`, `body`, `nodes`) rather than inkspire's (`meta`, `body`, `provenance`,
`context_summary`); `check` validates `meta` only as YAML and as a mapping, not inkspire's
own header fields; inkspire's functions for its own header fields (`header_fields`,
`with_header`, `display_name`) and for rewriting one section in place (`render_with`) are
left out; messages and docstrings say "body" or "text" where inkspire's say "prose"; and
`dump_yaml` comes with it from inkspire's `inkspire_api/fs.py`.
"""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

#: What one of these files is called.
SUFFIX = ".ink"

#: The five characters a fence line opens with. Exactly five, not five or more.
FENCE = "====="

#: What follows the fence, before the section's name.
FENCE_PREFIX = "ink:"

#: A YAML mapping of everything about the file that is not its body.
SECTION_META = "meta"

#: The file's main text.
SECTION_BODY = "body"

#: Per-node metadata, keyed by node id.
SECTION_NODES = "nodes"

#: The section names jiyuu gives a meaning to. Any other is kept but not understood.
KNOWN_SECTIONS = (SECTION_META, SECTION_BODY, SECTION_NODES)

#: The longest a section name may be.
MAX_NAME_LENGTH = 32

#: The characters a section name is made of.
NAME_CHARACTERS = frozenset(string.ascii_lowercase + "_")

#: How much of a file `read_header` reads, so that reading only the metadata of many files
#: does not load all of each of them.
MAX_HEADER_BYTES = 64 * 1024

ERROR = "error"
WARNING = "warning"


class _Dumper(yaml.SafeDumper):
    """Writes a value of several lines as a block, so it stays readable."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _represent_str)


def dump_yaml(document: dict) -> str:
    """`document` as YAML, keys in the order they were inserted.

    Anything YAML does not carry into a parsed document — comments, blank lines, quoting
    style — is not preserved by a read and a write through here.
    """
    return yaml.dump(
        document,
        Dumper=_Dumper,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )


@dataclass(frozen=True)
class Document:
    """One parsed `.ink` file."""

    #: The `ink:meta` mapping. Empty when there is none, or when it could not be read.
    metadata: dict = field(default_factory=dict)
    #: The `ink:body` section, or the whole file where there are no sections.
    body: str = ""
    #: Every other section, by name, as text, in the order they were read.
    sections: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Problem:
    """Something `check` found, at the line it is on."""

    line: int
    level: str
    message: str


@dataclass(frozen=True)
class _Section:
    """One section as it was read: its name, its text, and the line its fence is on."""

    name: str
    text: str
    line: int


def fence_line(name: str) -> str:
    """The line that opens the section called `name`."""
    return f"{FENCE} {FENCE_PREFIX}{name}\n"


def section_name(line: str) -> str | None:
    """The name the fence line `line` opens, or `None` where it is not a fence line.

    Exactly five `=`, then at least one space, then `ink:`, then the name, then only
    spaces before the end of the line. A tab anywhere, a sixth `=`, or a name with a
    character outside `NAME_CHARACTERS` all mean this is an ordinary line of text.
    """
    if not line.startswith(FENCE):
        return None
    rest = line[len(FENCE) :].rstrip("\n").rstrip("\r")
    if not rest.startswith(" "):
        return None
    rest = rest.lstrip(" ")
    if not rest.startswith(FENCE_PREFIX):
        return None
    name = rest[len(FENCE_PREFIX) :].rstrip(" ")
    if not name or len(name) > MAX_NAME_LENGTH or not set(name) <= NAME_CHARACTERS:
        return None
    return name


def _read(text: str) -> list[_Section] | None:
    """`text`'s sections in the order they appear, or `None` where it has none.

    `None` covers the two cases that are all body and nothing else: a file with no fence
    line anywhere, and a file with text above its first fence. The second is malformed —
    `check` reports it — and is read this way because losing a section's metadata can be
    recovered from, while losing the body cannot.
    """
    found: list[tuple[str, int, list[str]]] = []
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        name = section_name(line)
        if name is not None:
            found.append((name, number, []))
        elif found:
            found[-1][2].append(line)
        else:
            return None
    if not found:
        return None
    return [_Section(name, "".join(lines), number) for name, number, lines in found]


def _mapping(header: str) -> dict:
    """`header` as a mapping, or empty where it is not one or is not YAML."""
    try:
        loaded = yaml.safe_load(header)
    except yaml.YAMLError as error:
        logger.warning("the meta section could not be parsed: %s", error)
        return {}
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        logger.warning("the meta section is not a mapping: %r", loaded)
        return {}
    return loaded


def parse(text: str) -> Document:
    """`text` as metadata, a body and whatever other sections it carries.

    A file with no sections is all body, with no metadata and no sections. A section named
    twice keeps its last occurrence, as a YAML mapping would.
    """
    sections = _read(text)
    if sections is None:
        return Document(metadata={}, body=text, sections={})

    held: dict[str, str] = {}
    for section in sections:
        if section.name in held:
            logger.warning(
                'the section "%s" appears more than once; the last one wins', section.name
            )
        held[section.name] = section.text

    header = held.pop(SECTION_META, None)
    body = held.pop(SECTION_BODY, "")
    return Document(metadata=_mapping(header or ""), body=body, sections=held)


def render(metadata: dict, body: str, sections: dict[str, str]) -> str:
    """A file's text: `metadata`, then `body`, then `sections` in the order given.

    All three are required, because a section derived from the body must be written with
    it: a signature that defaulted either away would make writing a body without the
    section that describes it the easy mistake.

    With no metadata and no other sections, no fences are written at all, so a file that
    needs none is plain text. Keys are written in the order the mapping holds them, so a
    parsed header keeps its own order and anything new goes after it.

    A fence line must start a line, so a section with another after it is given a closing
    newline where it has none. That is the only byte a read and a write can change, and
    only once: everything this writes reads back as the same three parts.

    Raises `ValueError` on a body holding a line that would read back as a fence, rather
    than writing a file it could not parse. Escaping it silently would change the body.
    """
    for number, line in enumerate(body.splitlines(), start=1):
        if section_name(line) is not None:
            raise ValueError(
                f"line {number} of the body reads as a section fence: {line.strip()!r}"
            )

    if not metadata and not sections:
        return body

    parts: list[str] = []
    if metadata:
        parts.append(fence_line(SECTION_META))
        parts.append(dump_yaml(metadata))
    parts.append(fence_line(SECTION_BODY))
    parts.append(body)
    for name, text in sections.items():
        if parts[-1] and not parts[-1].endswith("\n"):
            parts.append("\n")
        parts.append(fence_line(name))
        parts.append(text)
    return "".join(parts)


def read_header(path: Path) -> dict:
    """The `ink:meta` mapping of the file at `path`, without reading all of it.

    A file that cannot be read, or that does not open with a `meta` section, has no
    metadata. So does one whose `meta` section is longer than `MAX_HEADER_BYTES`, which
    is told from a short file by whether the read stopped at the budget or at the end of
    the file: a `meta` section with nothing after it is the whole file only in the second
    case.
    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            start = handle.read(MAX_HEADER_BYTES)
    except (OSError, UnicodeDecodeError) as error:
        logger.warning("%s could not be read: %s", path, error)
        return {}

    sections = _read(start)
    if not sections or sections[0].name != SECTION_META:
        return {}
    if len(sections) < 2 and len(start) == MAX_HEADER_BYTES:
        return {}
    return _mapping(sections[0].text)


def _header_problems(section: _Section) -> list[Problem]:
    """Everything wrong with a `meta` section as YAML: not parseable, or not a mapping.
    What its keys mean is left to whatever reads them."""
    try:
        loaded = yaml.safe_load(section.text)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = mark.line + section.line + 1 if mark is not None else section.line
        detail = getattr(error, "problem", None) or "it is not YAML"
        return [Problem(line, ERROR, f"the meta section is not valid YAML: {detail}")]

    if loaded is not None and not isinstance(loaded, dict):
        return [
            Problem(
                section.line + 1,
                ERROR,
                "the meta section has to be a mapping of keys to values (this is "
                f"{type(loaded).__name__})",
            )
        ]
    return []


def check(text: str) -> list[Problem]:
    """Everything wrong with `text`'s sections, in line order, worst first on a line.

    A file with no sections has nothing to report: it is all body, and the body is not
    examined here.
    """
    sections = _read(text)
    if sections is None:
        if any(section_name(line) is not None for line in text.splitlines()):
            return [Problem(1, ERROR, "the file has text above its first section")]
        return []

    problems: list[Problem] = []
    seen: set[str] = set()
    for index, section in enumerate(sections):
        if section.name in seen:
            problems.append(
                Problem(
                    section.line,
                    ERROR,
                    f'the section "{section.name}" is opened more than once',
                )
            )
        seen.add(section.name)

        if section.name == SECTION_META:
            if index != 0:
                problems.append(
                    Problem(
                        section.line,
                        ERROR,
                        "the meta section has to come first, or reading only the header "
                        "will not find it",
                    )
                )
            problems.extend(_header_problems(section))
        elif section.name not in KNOWN_SECTIONS:
            problems.append(
                Problem(
                    section.line,
                    WARNING,
                    f'the section "{section.name}" means nothing here',
                )
            )

    problems.sort(key=lambda problem: (problem.line, problem.level))
    return problems
