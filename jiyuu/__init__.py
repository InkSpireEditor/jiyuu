"""jiyuu: a mindmap viewer and editor.

jiyuu reads and writes FreeMind/Freeplane `.mm` files, and stores its own maps as `.ink`
files — a plain text format with a YAML header, editable with any text editor. A map is a
tree of nodes with a single root, rendered with the root in the centre and its descendants
growing to the left and right of it.
The version number is read from the installed package's metadata, so `pyproject.toml` is
the only place it is written.
"""

from importlib.metadata import version

__version__ = version("jiyuu")
