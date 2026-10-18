"""The window's File menu, and exporting the map from it to other formats.

An export writes a new file and nothing else: the map's own file and the way it is saved
are unchanged. A name already in use is refused rather than written over, since the file
may be one the map was read from, holding data that jiyuu does not read.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

from ..document import Document, free_path
from ..formats import mm, write_text_atomically
from ..model import MindMap
from ..theme import Theme
from .dialogs import FileNameDialog

#: Each format the map can be exported to: the menu item's label, the file suffix, and the
#: function that writes a map in that format.
FORMATS: list[tuple[str, str, Callable[[MindMap], str]]] = [
    ("Export as .mm…", ".mm", mm.write),
]


def file_menu(page: ft.Page, theme: Theme, doc: Document, on_closed: Callable[[], None]) -> ft.MenuBar:
    """A menu bar with a File menu holding one export item per format in `FORMATS`.
    `on_closed` is called when an export dialog closes."""
    colors = theme.root
    style = ft.MenuStyle(bgcolor=colors.background)
    items: list[ft.Control] = [
        ft.MenuItemButton(
            content=ft.Text(label, color=colors.text),
            on_click=lambda _event, suffix=suffix, writer=writer: ask_export(
                page, theme, doc, suffix=suffix, writer=writer, on_closed=on_closed
            ),
        )
        for label, suffix, writer in FORMATS
    ]
    return ft.MenuBar(
        style=style,
        controls=[ft.SubmenuButton(content=ft.Text("File", color=colors.text), menu_style=style, controls=items)],
    )


def ask_export(
    page: ft.Page,
    theme: Theme,
    doc: Document,
    *,
    suffix: str,
    writer: Callable[[MindMap], str],
    on_closed: Callable[[], None],
) -> FileNameDialog:
    """Shows a dialog asking for a new file to export `doc`'s map to with `writer`, in
    the folder of the map's file, suggesting the first free name with `suffix`; returns
    the dialog."""
    current = doc.path or doc.source
    dialog = FileNameDialog(
        page,
        theme,
        title=f"Export as {suffix}",
        message=f"The map is written to a new file; {current.name} is not changed.",
        folder=current.parent,
        suggestion=free_path(current.with_suffix(suffix)).name,
        suffix=suffix,
        action="Export",
        on_chosen=lambda path: write_new_file(path, writer(doc.mindmap)),
        on_closed=on_closed,
        cancellable=True,
    )
    dialog.show()
    return dialog


def write_new_file(path: Path, text: str) -> str | None:
    """Writes `text` to `path`, which must not exist yet; returns why it was not written,
    or `None` once it was."""
    if path.exists():
        return f"{path.name} already exists"
    try:
        write_text_atomically(path, text)
    except OSError as error:
        return str(error)
    return None
