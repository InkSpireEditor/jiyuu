"""Dialogs in the window's theme: one asking for the name of a new file, and one making a
node a task or changing its task.

Flet's own file picker needs Zenity on Linux, which is not always installed, so a file name
is typed instead, into a field prefilled with a suggestion. The file goes in a folder fixed
by whoever opens the dialog; a name typed with folders in it is taken relative to that
folder.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import flet as ft

from ..formats.body import is_due_date
from ..model import PRIORITIES, Task
from ..theme import Theme

#: The priority dropdown's option for a task with no priority. Not one of `PRIORITIES`.
NO_PRIORITY = "none"
#: The label of each priority in the dropdown.
PRIORITY_LABELS = {NO_PRIORITY: "None", "H": "H (high)", "M": "M (medium)", "L": "L (low)"}


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


class TaskDialog:
    """A modal dialog setting a node's due date and priority, which makes the node a task if
    it is not one yet.

    `task` is the node's task, or `None` for a plain node. Save calls `on_chosen` with the
    task the fields describe, done or not as `task` was; "Not a task", shown only when
    `task` is set, calls it with `None`. The due date typed is turned into one by
    `resolve_due` on Save, which returns `None` for a value it cannot read: the field then
    shows an error, and the dialog stays open. By default only a date written `YYYY-MM-DD`
    or `YYYY-MM-DDTHH:MM` is read. `on_closed` is called once the dialog closes, whichever
    way, Cancel included.
    """

    def __init__(
        self,
        page: ft.Page,
        theme: Theme,
        *,
        text: str,
        task: Task | None,
        on_chosen: Callable[[Task | None], None],
        on_closed: Callable[[], None],
        resolve_due: Callable[[str], str | None] = lambda value: value if is_due_date(value) else None,
        due_hint: str = "YYYY-MM-DD or YYYY-MM-DDTHH:MM",
    ) -> None:
        self.page = page
        self.task = task
        self.resolve_due = resolve_due
        self.due_hint = due_hint
        self.on_chosen = on_chosen
        self.on_closed = on_closed
        self.open = False
        colors = theme.root
        self.due = ft.TextField(
            label=f"Due: {due_hint}; empty for none",
            value=task.due if task is not None and task.due else "",
            autofocus=True,
            color=colors.text,
            cursor_color=colors.text,
            border_color=theme.edge,
            on_submit=self._save,
        )
        self.priority = ft.Dropdown(
            label="Priority",
            value=task.priority if task is not None and task.priority else NO_PRIORITY,
            options=[ft.DropdownOption(key=key, text=label) for key, label in PRIORITY_LABELS.items()],
            color=colors.text,
            border_color=theme.edge,
        )
        actions: list[ft.Control] = [ft.TextButton(content=ft.Text("Save", color=colors.text), on_click=self._save)]
        if task is not None:
            actions.append(ft.TextButton(content=ft.Text("Not a task", color=colors.text), on_click=self._unset))
        actions.append(ft.TextButton(content=ft.Text("Cancel", color=colors.text), on_click=self._cancel))
        self.dialog = ft.AlertDialog(
            modal=True,
            bgcolor=colors.background,
            title=ft.Text("Task" if task is not None else "Make a task", color=colors.text),
            content=ft.Column(
                tight=True,
                controls=[ft.Text(text, color=colors.text), self.due, self.priority],
            ),
            actions=actions,
            on_dismiss=self._on_dismiss,
        )

    def show(self) -> None:
        """Opens the dialog."""
        self.open = True
        self.page.show_dialog(self.dialog)

    def chosen_task(self) -> Task | None:
        """The task the fields describe, or `None` while the due date cannot be read."""
        typed = (self.due.value or "").strip()
        due = self.resolve_due(typed) if typed else None
        if typed and due is None:
            return None
        priority = self.priority.value if self.priority.value in PRIORITIES else None
        done = self.task is not None and self.task.done
        return Task(done=done, due=due, priority=priority)

    def _save(self, _event: ft.Event) -> None:
        task = self.chosen_task()
        if task is None:
            self.due.error = f"not a date: {self.due_hint}"
            self.page.update(self.due)
            return
        self.on_chosen(task)
        self._close()

    def _unset(self, _event: ft.Event) -> None:
        self.on_chosen(None)
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
        # As in `FileNameDialog`: only a dismissal that did not come from `_close` still
        # has anything to do.
        if self.open:
            self.open = False
            self.on_closed()
