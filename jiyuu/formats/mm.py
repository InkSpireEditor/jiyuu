"""Reads and writes FreeMind/Freeplane `.mm` files.

A `.mm` file is XML: one `<map>` element holding one `<node>` tree. A node's text comes
from its `TEXT` attribute, or, failing that, from a `<richcontent TYPE="NODE">` child's
embedded HTML; its `FOLDED` attribute and, on a first-level node, its `POSITION` attribute
carry over directly. Everything else FreeMind or Freeplane can write into one of these files
— styles, attributes, icons, notes, clones, and more — is outside what this reads: it is
either silently skipped, where it is a recognised but unsupported feature, or dropped with a
warning, where it is not recognised at all. Nothing it does not understand ever stops the
read or loses the node text that is there; `read`'s second return value is the list of
things it had to let go of.

Parsed with `defusedxml`, never the standard library's `xml.etree.ElementTree` directly: a
`.mm` file is not a trusted input, and `defusedxml` refuses external entities, external DTD
references, and in-document entity expansion (the "billion laughs" attack) that the standard
library's own parser would otherwise allow.

`write` produces a file Freeplane can open: each node's text, folding, and, on a first-level
node, its side, with an `ID` attribute numbering the nodes in the order they are written.
The standard library's `xml.etree.ElementTree` builds it; only parsing an untrusted file
needs `defusedxml`.
"""

from __future__ import annotations

from xml.etree import ElementTree as StdET
from xml.etree.ElementTree import Element  # parsing goes through ET below, building through StdET

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException

from ..model import MindMap, Node

#: Child element names a `<node>` or `<map>` is allowed to carry without this reader
#: warning about them, because they are recognised but deliberately out of scope rather
#: than simply unknown. A `<richcontent>` is in this set unconditionally: whether it is
#: read as text or skipped is decided by `_node_text`, not by this list.
_RECOGNISED_BUT_UNSUPPORTED = frozenset({"richcontent"})


def _plain_text(richcontent: Element, warnings: list[str]) -> str:
    """The plain text inside a `<richcontent TYPE="NODE">` element's embedded HTML.

    Every text fragment `richcontent` contains, in document order, joined with a single
    space between each pair — so a `<p>` boundary, a `<br/>`, or a literal newline inside
    the HTML all collapse to the same thing: one line break becomes one space. A warning is
    recorded only when there was more than one fragment, or a literal newline, to collapse;
    the common case of one plain line of text produces none.
    """
    fragments = [fragment for fragment in richcontent.itertext() if fragment.strip()]
    collapsed = " ".join(" ".join(fragment.split()) for fragment in fragments)
    if len(fragments) > 1 or any("\n" in fragment or "\r" in fragment for fragment in fragments):
        warnings.append("collapsed a line break in a node's rich text to a space")
    return collapsed


def _node_text(element: Element, warnings: list[str]) -> str:
    """The text for `element`: its `TEXT` attribute, its `<richcontent TYPE="NODE">`
    child's text, or, failing both, an empty string with a warning.

    The empty-string case is a cloned node: Freeplane lets a node carry no text and no
    rich content of its own, instead pointing at another node to copy from by a mechanism
    this reader does not resolve, so a clone reads as an empty node rather than losing its
    place in the tree.
    """
    text = element.get("TEXT")
    if text is not None:
        return text
    richcontent = element.find("richcontent")
    if richcontent is not None and richcontent.get("TYPE") == "NODE":
        return _plain_text(richcontent, warnings)
    warnings.append("a <node> with neither TEXT nor rich text (likely a clone) read as empty")
    return ""


def _read_node(element: Element, *, depth: int, warnings: list[str]) -> Node:
    """`element` and everything under it, as a `Node` tree.

    `depth` is `element`'s own distance from the map's root — `0` for the root itself, `1`
    for a first-level node, more for everything deeper. `POSITION` is read only at depth
    `1`, since only a child of the root is drawn on a side of its own.
    """
    node = Node(text=_node_text(element, warnings))
    node.folded = element.get("FOLDED") == "true"

    if depth == 1:
        position = element.get("POSITION")
        if position in ("left", "right"):
            node.side = position
        elif position is not None:
            warnings.append(f"ignored POSITION={position!r} on node {node.text!r}")

    for child in element:
        if child.tag == "node":
            node.children.append(_read_node(child, depth=depth + 1, warnings=warnings))
        elif child.tag not in _RECOGNISED_BUT_UNSUPPORTED:
            warnings.append(f"dropped <{child.tag}> on node {node.text!r}")

    return node


def read(text: str) -> tuple[MindMap | None, list[str]]:
    """`text`, as a `.mm` file, parsed into a `MindMap`.

    Returns `(None, warnings)` if `text` cannot be read as XML at all, or has no `<node>`
    under its `<map>` to use as a root — the only two cases where there is nothing to
    return a tree for. Every other problem is reported as a warning alongside a tree that
    is still as complete as it could be made.
    """
    warnings: list[str] = []
    try:
        root_element = ET.fromstring(text)
    except (ET.ParseError, DefusedXmlException) as error:
        warnings.append(f"could not be parsed as XML: {error}")
        return None, warnings

    node_elements = [child for child in root_element if child.tag == "node"]
    for child in root_element:
        if child.tag != "node" and child.tag not in _RECOGNISED_BUT_UNSUPPORTED:
            warnings.append(f"dropped <{child.tag}> at the map level")

    if not node_elements:
        warnings.append("no <node> found under <map>; nothing to read")
        return None, warnings
    if len(node_elements) > 1:
        warnings.append(f"found {len(node_elements)} top-level <node> elements; using the first")

    root = _read_node(node_elements[0], depth=0, warnings=warnings)
    return MindMap(root=root), warnings


#: The `version` attribute written on `<map>`: the Freeplane release whose format `write`
#: follows.
MAP_VERSION = "freeplane 1.9.13"


def write(mindmap: MindMap) -> str:
    """`mindmap` as the text of a `.mm` file.

    Each node becomes a `<node>` with its text as `TEXT`, `FOLDED="true"` if it is folded,
    and, on a first-level node with a side, `POSITION="left"` or `"right"`; nodes are nested
    as in the tree. Every node also gets `ID="ID_<n>"`, `n` counting from 1 in the order
    the nodes are written, since Freeplane expects every node to have one. Metadata jiyuu
    keeps on a node but has no `.mm` attribute for is not written.

    Characters outside ASCII are written as character references (`&#233;`), which every
    XML reader decodes the same way whatever encoding it assumes for the file.
    """
    root = StdET.Element("map", version=MAP_VERSION)
    counter = [0]

    def add(parent: Element, node: Node, depth: int) -> None:
        counter[0] += 1
        element = StdET.SubElement(parent, "node", TEXT=node.text, ID=f"ID_{counter[0]}")
        if node.folded:
            element.set("FOLDED", "true")
        if depth == 1 and node.side in ("left", "right"):
            element.set("POSITION", node.side)
        for child in node.children:
            add(element, child, depth + 1)

    add(root, mindmap.root, 0)
    StdET.indent(root)
    return StdET.tostring(root, encoding="us-ascii").decode("ascii") + "\n"
