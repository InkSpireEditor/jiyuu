"""A map's tree as the text of an `.ink` file's `ink:body` section: an indented list.

Each node is one line: two spaces per level of depth, `- `, then the node's text. The
root is the first line, at no indentation:

    - Project
      - Goals
        - I/O
        - [ ] Foo  due:2026-10-25 priority:H
        - [x] Bar
      - Risks

A node that is a task has a checkbox before its text, as in a Markdown task list: `[ ]`
when it is not done, `[x]` when it is. After the text, separated from it by two spaces, come
the task's fields, each written `name:value`: `due:` (an ISO date, or a date and a time to
the minute, `due:2026-10-25T14:00`) then `priority:` (`H`, `M` or `L`). A field that is not
set is left out.

`write` always writes exactly that form. Every line starts with spaces or `-`, so a body
written here can never contain a line that reads as an `.ink` section fence (which starts
with `=====`).

`read` accepts more than `write` produces, since a body may have been edited by hand in
any text editor: `*` or `+` as the marker, any indentation width, tabs, blank lines, `[X]`
for a done task, one space or several before a task's fields, and the fields in either
order. A line's depth comes from comparing its indentation with the lines above it — deeper
than the line above makes it a child, the same as a sibling, shallower closes back to the
nearest line at that indentation or less — so four-space or tab indentation reads into the
same tree as two-space. Reading never drops a line's text: a line it cannot place where it
belongs is still attached to the tree, and reported in the list of problems returned
alongside it. In the same way, a field whose value is not valid, and a checkbox on the root
(which cannot be a task), are reported and read as part of the text.

Two escapes keep any text readable back as it was written:

- A node that is not a task, whose text starts with a checkbox or with a backslash, is
  written with a backslash in front (`- \\[ ] not a task`); reading removes one leading
  backslash from a line with no checkbox.
- On a task's line, words at the end of the text that start with `due:` or `priority:`
  would read as fields; each is written with a backslash before its colon
  (`- [ ] Foo due\\:soon`), and reading removes it.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .ink import ERROR, WARNING, Problem
from ..model import PRIORITIES, Node, Task

#: What one level of depth is indented by.
INDENT = "  "
#: What comes before a node's text on its line.
MARKER = "- "
#: The characters `read` accepts as a line's marker.
MARKERS = "-*+"
#: The checkbox of a task that is not done, and of one that is.
CHECKBOX = "[ ]"
CHECKBOX_DONE = "[x]"
#: Each checkbox `read` accepts, and whether it means done.
CHECKBOXES = {CHECKBOX: False, CHECKBOX_DONE: True, "[X]": True}
#: What separates a task's text from its fields.
FIELD_SEPARATOR = "  "
#: The names of a task's fields, in the order `write` writes them.
FIELDS = ("due", "priority")
#: Starts the text of a line whose text would otherwise read as something else.
ESCAPE = "\\"

#: The last field of a task line: `name:value` at the end, after a space or at the start.
_LAST_FIELD = re.compile(r"(?:^|\s+)(" + "|".join(FIELDS) + r"):(\S+)$")
#: A word of a task's text that would read as a field once its backslashes are removed:
#: the field's name, any number of backslashes, then the colon.
_FIELD_LIKE = re.compile(r"^(" + "|".join(FIELDS) + r")(\\*):")
#: A due date as `write` writes it: a date, or a date and a time to the minute.
_DUE = re.compile(r"^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?$")


def is_due_date(value: str) -> bool:
    """Whether `value` is a due date as a task field holds it: an existing date written
    `YYYY-MM-DD`, or a date and time written `YYYY-MM-DDTHH:MM`."""
    if not _DUE.match(value):
        return False
    try:
        if "T" in value:
            datetime.fromisoformat(value)
        else:
            date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _split_line(line: str) -> tuple[str, bool, str]:
    """A line's leading whitespace, whether it has a marker, and its text.

    A marker is one of `MARKERS` followed by a space, or one of them alone on the line —
    which is how an editor that trims trailing spaces leaves a node with empty text,
    written as `- `. Anything else is all text, with no marker.
    """
    stripped = line.lstrip(" \t")
    indentation = line[: len(line) - len(stripped)]
    content = stripped.rstrip()
    if content and content[0] in MARKERS and (len(content) == 1 or content[1] == " "):
        return indentation, True, content[1:].strip()
    return indentation, False, content


def _split_checkbox(text: str) -> tuple[bool | None, str]:
    """Whether `text` starts with a checkbox meaning done (`True`) or not done (`False`),
    or `None` if it has none; and the rest of `text` after the checkbox.

    A checkbox counts only when the text ends right after it or a space follows it, so
    `[x]y` is text.
    """
    for box, done in CHECKBOXES.items():
        if text == box or text.startswith(box + " "):
            return done, text[len(box) :].strip()
    return None, text


def _trailing_field_like(words: list[str]) -> int:
    """How many of the last `words` would read as fields once their backslashes are
    removed: the index from which every word matches `_FIELD_LIKE`."""
    start = len(words)
    while start > 0 and _FIELD_LIKE.match(words[start - 1]):
        start -= 1
    return start


def _escape_task_text(text: str) -> str:
    """`text` with one more backslash before the colon of each word at its end that would
    otherwise read as a field."""
    words = text.split(" ")
    for i in range(_trailing_field_like(words), len(words)):
        words[i] = _FIELD_LIKE.sub(lambda match: f"{match[1]}{match[2]}{ESCAPE}:", words[i], count=1)
    return " ".join(words)


def _unescape_task_text(text: str) -> str:
    """`text` with one backslash removed before the colon of each word at its end that
    `_escape_task_text` would have escaped, where there is one to remove."""
    words = text.split(" ")
    for i in range(_trailing_field_like(words), len(words)):
        words[i] = _FIELD_LIKE.sub(lambda match: f"{match[1]}{match[2][1:]}:", words[i], count=1)
    return " ".join(words)


def _field_problem(name: str, value: str, found: dict[str, str]) -> str | None:
    """Why field `name:value` cannot be read as one, given the fields already found after
    it on the same line; `None` if it can."""
    if name in found:
        return f"{name}: is given twice; the first is read as text"
    if name == "due" and not is_due_date(value):
        return f"due:{value} is not a date written YYYY-MM-DD or YYYY-MM-DDTHH:MM; read as text"
    if name == "priority" and value not in PRIORITIES:
        return f"priority:{value} is not one of {', '.join(PRIORITIES)}; read as text"
    return None


def _read_task(done: bool, rest: str, number: int, problems: list[Problem]) -> tuple[str, Task]:
    """The text and task of a task line, from what follows its checkbox.

    Fields are taken from the end of `rest` one at a time, until a word is not a field or
    is not a valid one; that word, and everything before it, is the text.
    """
    found: dict[str, str] = {}
    while (match := _LAST_FIELD.search(rest)) is not None:
        name, value = match[1], match[2]
        problem = _field_problem(name, value, found)
        if problem is not None:
            problems.append(Problem(number, WARNING, problem))
            break
        found[name] = value
        rest = rest[: match.start()]
    task = Task(done=done, due=found.get("due"), priority=found.get("priority"))
    return _unescape_task_text(rest.strip()), task


def _read_node(content: str, number: int, is_root: bool, problems: list[Problem]) -> Node:
    """The node a line's `content`, after its marker, describes."""
    done, rest = _split_checkbox(content)
    if done is None:
        return Node(text=content[1:] if content.startswith(ESCAPE) else content)
    if is_root:
        problems.append(Problem(number, WARNING, "the root cannot be a task; its checkbox is read as text"))
        return Node(text=content)
    text, task = _read_task(done, rest, number, problems)
    return Node(text=text, task=task)


def read(text: str) -> tuple[Node | None, list[Problem]]:
    """The tree in body `text`, and every problem found reading it.

    Problems are numbered by line within `text`, from 1. Returns `None` for the tree only
    when `text` has no non-blank line at all.
    """
    lines = [(number, line) for number, line in enumerate(text.splitlines(), start=1) if line.strip()]
    if not lines:
        return None, [Problem(1, ERROR, "the body is empty: there is no root node")]

    problems: list[Problem] = []
    root: Node | None = None
    open_nodes: list[tuple[int, Node]] = []  # (indentation, node), root first
    indent_kinds: set[str] = set()  # which of " " and "\t" the indentation has used so far

    for number, line in lines:
        indentation, has_marker, content = _split_line(line)
        if not has_marker:
            problems.append(Problem(number, WARNING, "this line has no '-', '*' or '+' marker"))
        if len(indent_kinds) < 2 and len(indent_kinds | set(indentation)) == 2:
            problems.append(Problem(number, WARNING, "tabs and spaces are mixed in the indentation"))
        indent_kinds |= set(indentation)
        depth = len(indentation)
        node = _read_node(content, number, root is None, problems)

        if root is None:
            root = node
            open_nodes = [(depth, node)]
            continue

        while len(open_nodes) > 1 and depth <= open_nodes[-1][0]:
            open_nodes.pop()
        parent_depth, parent = open_nodes[-1]
        if depth == parent_depth:  # only the root is open, and this line is level with it
            problems.append(
                Problem(number, ERROR, "a second top-level line; read as a child of the first")
            )
        elif depth < parent_depth:  # only the root is open, and this line is left of it
            problems.append(
                Problem(
                    number,
                    WARNING,
                    "indented less than the root; read as a child of the root",
                )
            )
        parent.children.append(node)
        open_nodes.append((depth, node))

    return root, problems


def line_content(node: Node, is_root: bool = False) -> str:
    """What `write` puts after a node's marker: its text, with its task's checkbox and
    fields if it is a task, escaped so that `read` gives the same text and task back. The
    root is written without a task, since it cannot be one."""
    task = None if is_root else node.task
    if task is None:
        escape = node.text.startswith(ESCAPE) or _split_checkbox(node.text)[0] is not None
        return ESCAPE + node.text if escape else node.text
    content = CHECKBOX_DONE if task.done else CHECKBOX
    if node.text:
        content += " " + _escape_task_text(node.text)
    values = {"due": task.due, "priority": task.priority}
    fields = [f"{name}:{values[name]}" for name in FIELDS if values[name]]
    if fields:
        content += FIELD_SEPARATOR + " ".join(fields)
    return content


def write(root: Node) -> str:
    """The tree under `root`, root included, as body text: one line per node, `\\n` line
    endings, a final newline. Folded nodes' children are written too: folding hides a
    branch from view, it does not remove it from the map."""
    lines: list[str] = []

    def emit(node: Node, depth: int) -> None:
        lines.append(f"{INDENT * depth}{MARKER}{line_content(node, depth == 0)}\n")
        for child in node.children:
            emit(child, depth + 1)

    emit(root, 0)
    return "".join(lines)
