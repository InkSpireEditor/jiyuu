"""A dialog asking for the name of a new file, in the window's theme.

Flet's own file picker needs Zenity on Linux, which is not always installed, so a file name
is typed instead, into a field prefilled with a suggestion. The file goes in a folder fixed
by whoever opens the dialog; a name typed with folders in it is taken relative to that
folder.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

from ..theme import Theme


class FileNameDialog:
    """A modal dialog asking for a file name in `folder`, ending in `suffix`.

    `suffix` is added to a name typed without it. `on_chosen` is called with the file's
    path once a name is confirmed, and returns `None` if it used the file, which closes the
    dialog, or a message saying why not, shown under the field while the dialog stays open.
    `on_closed` is called once the dialog closes, whichever way. Without `cancellable`,
    the only way out is to choose a name.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: Theme,
        *,
        title: str,
        message: str,
        folder: Path,
        suggestion: str,
        suffix: str,
        action: str,
        on_chosen: Callable[[Path], str | None],
        on_closed: Callable[[], None],
        cancellable: bool,
    ) -> None:
        self.page = page
        self.folder = folder
        self.suffix = suffix
        self.on_chosen = on_chosen
        self.on_closed = on_closed
        self.open = False
        colors = theme.root
        self.field = ft.TextField(
            value=suggestion,
            autofocus=True,
            color=colors.text,
            cursor_color=colors.text,
            border_color=theme.edge,
            on_submit=self._choose,
        )
        actions: list[ft.Control] = [
            ft.TextButton(content=ft.Text(action, color=colors.text), on_click=self._choose)
        ]
        if cancellable:
            actions.append(ft.TextButton(content=ft.Text("Cancel", color=colors.text), on_click=self._cancel))
        self.dialog = ft.AlertDialog(
            modal=True,
            bgcolor=colors.background,
            title=ft.Text(title, color=colors.text),
            content=ft.Column(tight=True, controls=[ft.Text(message, color=colors.text), self.field]),
            actions=actions,
            on_dismiss=self._on_dismiss,
        )

    def show(self) -> None:
        """Opens the dialog."""
        self.open = True
        self.page.show_dialog(self.dialog)

    def path(self) -> Path | None:
        """The file named in the field, in `folder`, with `suffix` added if it was not
        typed; `None` while the field is blank."""
        name = (self.field.value or "").strip()
        if not name:
            return None
        path = Path(name)
        if path.suffix != self.suffix:
            path = path.with_name(path.name + self.suffix)
        return self.folder / path

    def _choose(self, _event: ft.Event) -> None:
        path = self.path()
        if path is None:
            return
        error = self.on_chosen(path)
        if error is not None:
            self.field.error = error
            self.page.update(self.field)
            return
        self._close()

    def _cancel(self, _event: ft.Event) -> None:
        self._close()

    def _close(self) -> None:
        if not self.open:
            return
        self.open = False
        self.page.pop_dialog()
        self.on_closed()

    def _on_dismiss(self, _event: ft.Event) -> None:
        # Closing the dialog through `_close` dismisses it too; only a dismissal that did
        # not come from `_close` still has anything to do.
        if self.open:
            self.open = False
            self.on_closed()
