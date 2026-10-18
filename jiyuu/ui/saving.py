"""Saving the window's map as it changes, and asking what to do when it cannot be saved.

The saving itself is `jiyuu.document`'s; this module runs it from the window and shows what
it needs from the user:

- a banner when the map's file was changed by something else, offering "Reload" (read the
  file again, dropping the changes made in the window) or "Keep mine" (write the window's
  map over the file). The file is checked every `WATCH_INTERVAL` seconds, as well as
  before each save, so the banner appears soon after the change, whether or not the map
  was changed in the window since;
- a banner when a save fails, offering "Retry";
- a dialog asking for a file name, when the map has none yet, before the first change to it
  is saved.

Saves and checks run on the page's event loop, which is also where Flet calls the window's
own event handlers, so neither runs while a change to the map is half made.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

import flet as ft

from ..document import Autosave, Document, changed_on_disk, free_path, keep_mine, reload, save_as
from ..formats import ink
from ..model import MindMap
from ..theme import Theme

#: How often the map's file is checked for changes made by something else, in seconds.
WATCH_INTERVAL = 1.0


def window_title(doc: Document) -> str:
    """The window's title for `doc`: the name of the file it is saved to, or of the file it
    was opened from while it has none."""
    return f"{(doc.path or doc.source).name} — jiyuu"


class Saving:
    """Saves one window's map as it changes, and shows the banner and dialog that saving
    needs.

    `on_reload` is called with the map read again from disk, for the window to show it
    instead of its own. `on_done` is called when a banner or dialog that took the keyboard
    closes, for the window to take the keyboard back.
    """

    def __init__(
        self,
        page: ft.Page,
        doc: Document,
        theme: Theme,
        on_reload: Callable[[MindMap], None],
        on_done: Callable[[], None],
    ) -> None:
        self.page = page
        self.doc = doc
        self.theme = theme
        self.on_reload = on_reload
        self.on_done = on_done
        self.autosave = Autosave(doc, self._schedule, self._show_conflict)
        #: The banner or the file name dialog shown, if any.
        self.shown: ft.Banner | ft.AlertDialog | None = None
        #: The field the file name is typed in, while the dialog is shown.
        self.name_field: ft.TextField | None = None
        page.run_task(self._watch)

    def changed(self) -> None:
        """Records a change to the map: it is saved shortly, or, if the map has no file yet,
        a file name is asked for first."""
        self.autosave.changed()
        if self.doc.path is None and self.shown is None:
            self._ask_name()

    def _schedule(self, delay: float, callback: Callable[[], None]) -> Callable[[], object]:
        """Runs `callback` on the page's event loop after `delay` seconds; returns a function
        that cancels it. A save that fails is reported in a banner."""

        async def later() -> None:
            await asyncio.sleep(delay)
            try:
                callback()
            except OSError as error:
                self._show_banner(f"Could not save {self.doc.path}: {error}", [("Retry", self._retry)])

        return self.page.run_task(later).cancel

    async def _watch(self) -> None:
        """Checks the map's file every `WATCH_INTERVAL` seconds, for as long as the page runs."""
        while True:
            await asyncio.sleep(WATCH_INTERVAL)
            self.check_disk()

    def check_disk(self) -> None:
        """Shows the conflict banner if the map's file was changed by something else since
        it was last read or written, and drops any save waiting to happen. Does nothing
        while the map has no file, or the banner is already shown for it."""
        if self.doc.path is None or self.doc.conflicted:
            return
        if changed_on_disk(self.doc):
            self.doc.conflicted = True
            self.autosave.cancel()
            self._show_conflict()

    def _show_conflict(self) -> None:
        self._show_banner(
            f"{self.doc.path} was changed outside jiyuu. Changes made here are not saved until you choose.",
            [("Reload", self._reload), ("Keep mine", self._keep_mine)],
        )

    def _show_banner(self, message: str, actions: list[tuple[str, Callable[[ft.Event], None]]]) -> None:
        """Shows a banner with `message` and one button per `(label, handler)`, replacing
        any banner already shown."""
        if isinstance(self.shown, ft.Banner):
            self.page.pop_dialog()
        colors = self.theme.root
        self.shown = ft.Banner(
            bgcolor=colors.background,
            content=ft.Text(message, color=colors.text),
            actions=[
                ft.TextButton(content=ft.Text(label, color=colors.text), on_click=handler)
                for label, handler in actions
            ],
        )
        self.page.show_dialog(self.shown)

    def _close_shown(self) -> None:
        """Closes the banner or dialog shown, and hands the keyboard back."""
        self.shown = self.name_field = None
        self.page.pop_dialog()
        self.on_done()

    def _reload(self, _event: ft.Event) -> None:
        problems = reload(self.doc)
        if self.doc.conflicted:
            reasons = "; ".join(problem.message for problem in problems)
            self._show_banner(
                f"{self.doc.path} could not be read: {reasons}",
                [("Reload", self._reload), ("Keep mine", self._keep_mine)],
            )
            return
        self._close_shown()
        self.on_reload(self.doc.mindmap)

    def _keep_mine(self, _event: ft.Event) -> None:
        try:
            keep_mine(self.doc)
        except OSError as error:
            self._show_banner(
                f"Could not save {self.doc.path}: {error}",
                [("Reload", self._reload), ("Keep mine", self._keep_mine)],
            )
            return
        self._close_shown()

    def _retry(self, _event: ft.Event) -> None:
        self._close_shown()
        self.autosave.changed()

    def _ask_name(self) -> None:
        """Shows a dialog asking for the name of a new `.ink` file to save the map to, in
        the folder of the file it was opened from, suggesting the first free name."""
        colors = self.theme.root
        suggestion = free_path(self.doc.source.with_suffix(ink.SUFFIX)).name
        self.name_field = ft.TextField(
            value=suggestion,
            autofocus=True,
            color=colors.text,
            cursor_color=colors.text,
            border_color=self.theme.edge,
            on_submit=self._save_as,
        )
        existing = self.doc.source.with_suffix(ink.SUFFIX).name
        self.shown = ft.AlertDialog(
            modal=True,
            bgcolor=colors.background,
            title=ft.Text("Save changes as", color=colors.text),
            content=ft.Column(
                tight=True,
                controls=[
                    ft.Text(
                        f"{existing} already exists, and may hold changes made earlier. "
                        "Choose a new file for this map's changes.",
                        color=colors.text,
                    ),
                    self.name_field,
                ],
            ),
            actions=[ft.TextButton(content=ft.Text("Save", color=colors.text), on_click=self._save_as)],
            on_dismiss=self._on_dismiss,
        )
        self.page.show_dialog(self.shown)

    def _save_as(self, _event: ft.Event) -> None:
        if self.name_field is None:
            return
        name = (self.name_field.value or "").strip()
        if not name:
            return
        path = Path(name)
        if path.suffix != ink.SUFFIX:
            path = path.with_name(path.name + ink.SUFFIX)
        target = self.doc.source.parent / path
        try:
            save_as(self.doc, target)
        except FileExistsError:
            self.name_field.error = f"{target.name} already exists"
            self.page.update(self.name_field)
            return
        except OSError as error:
            self.name_field.error = str(error)
            self.page.update(self.name_field)
            return
        self.page.title = window_title(self.doc)
        self._close_shown()
        self.page.update()

    def _on_dismiss(self, _event: ft.Event) -> None:
        # The dialog closed without a name being chosen; it is asked for again at the next
        # change.
        if self.shown is not None and isinstance(self.shown, ft.AlertDialog):
            self.shown = self.name_field = None
            self.on_done()
