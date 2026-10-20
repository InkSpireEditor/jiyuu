"""Syncing the window's map with taskwarrior while it is open (see `jiyuu.tasksync`).

The window's map is synced after each save, and every `SYNC_INTERVAL` seconds, so that a
change made in taskwarrior, and a task becoming urgent, show within that time. Nothing is
synced while the map has no task and no task link.

The `task` commands of a sync run in a worker thread (`asyncio.to_thread`), so that the
window keeps answering while they run. That thread reads only a snapshot of the map's tasks,
taken on the page's event loop, and the result is applied there too. If the map changed in
the meantime, the result is dropped and the sync run again from a new snapshot: the result
could otherwise undo a change made while it ran.

The first sync also asks taskwarrior whether it can be run at all, and for the urgency from
which a task is drawn as urgent (`tasksync.urgent_threshold`). Without taskwarrior, a
banner says so once, and nothing is synced.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

import flet as ft

from .. import tasksync
from ..document import Document
from ..formats.body import is_due_date
from ..model import MindMap, walk
from ..taskwarrior import Taskwarrior, TaskwarriorError

#: How often the window's map is synced with taskwarrior, in seconds, besides after each save.
SYNC_INTERVAL = 60.0


def has_tasks(mindmap: MindMap) -> bool:
    """Whether `mindmap` has anything to sync: a task node, a task link, or an orphaned
    task link."""
    return bool(mindmap.orphan_tasks) or any(
        node.task is not None or node.task_link is not None for node in walk(mindmap.root)
    )


class WindowSync:
    """Syncs one window's map with taskwarrior.

    `version` returns a number that changes whenever the map is changed (`Editor.version`).
    `on_synced` is called on the event loop with the result of a sync, for the window to
    apply it (`tasksync.apply`). `notify` shows a message in the window.
    """

    def __init__(
        self,
        page: ft.Page,
        doc: Document,
        taskwarrior: Taskwarrior,
        *,
        version: Callable[[], int],
        on_synced: Callable[[tasksync.SyncResult], None],
        notify: Callable[[str], None],
    ) -> None:
        self.page = page
        self.doc = doc
        self.taskwarrior = taskwarrior
        self.version = version
        self.on_synced = on_synced
        self.notify = notify
        #: Whether taskwarrior can be run; `None` until the first sync asks.
        self.available: bool | None = None
        #: The urgency from which a task is drawn as urgent, once asked.
        self.threshold = tasksync.DEFAULT_URGENT
        #: When the map was last changed in the window, or else when its file was written.
        self.changed_at: datetime | None = None
        self.running = False
        self.again = False
        #: The message of the latest failed sync, shown once until a sync works again.
        self.failure: str | None = None
        page.run_task(self._every_interval)

    def changed(self) -> None:
        """Records that the map was changed in the window just now."""
        self.changed_at = datetime.now(UTC)

    def request(self) -> None:
        """Syncs the map soon; if a sync is running, runs another once it ends."""
        if self.running:
            self.again = True
            return
        self.running = True
        self.page.run_task(self._sync)

    def resolve_due(self, value: str) -> str | None:
        """The due date `value` means: itself if it is already one (see
        `body.is_due_date`), else what taskwarrior reads it as (`tomorrow`, `friday`), if
        taskwarrior can be run; `None` if it is neither."""
        if is_due_date(value):
            return value
        if self.available is False:
            return None
        try:
            return self.taskwarrior.calc(value)
        except (TaskwarriorError, ValueError):
            return None

    async def _every_interval(self) -> None:
        """Asks for a sync every `SYNC_INTERVAL` seconds, the first one straight away."""
        while True:
            self.request()
            await asyncio.sleep(SYNC_INTERVAL)

    def _map_time(self) -> datetime:
        """When the map last changed: in the window, or else when its file was written."""
        if self.changed_at is not None:
            return self.changed_at
        if self.doc.path is not None:
            try:
                return datetime.fromtimestamp(self.doc.path.stat().st_mtime, UTC)
            except OSError:
                pass
        return datetime.now(UTC)

    async def _sync(self) -> None:
        """Syncs until a result could be applied, or there is nothing to sync."""
        try:
            while True:
                self.again = False
                if self.doc.path is None or not has_tasks(self.doc.mindmap) or not await self._check():
                    return
                mindmap, version = self.doc.mindmap, self.version()
                snap = tasksync.snapshot(mindmap)
                try:
                    result = await asyncio.to_thread(
                        tasksync.run_sync, snap, self.taskwarrior, self.doc.path, self._map_time()
                    )
                except TaskwarriorError as error:
                    if str(error) != self.failure:
                        self.failure = str(error)
                        self.notify(f"Tasks could not be synced with taskwarrior: {error}")
                    return
                self.failure = None
                if self.doc.mindmap is mindmap and self.version() == version:
                    self.on_synced(result)
                else:
                    self.again = True
                if not self.again:
                    return
        finally:
            self.running = False

    async def _check(self) -> bool:
        """Whether taskwarrior can be run, asked at the first sync together with the urgent
        threshold; says so in a banner the first time it cannot."""
        if self.available is None:
            self.available = await asyncio.to_thread(self.taskwarrior.available)
            if self.available:
                self.threshold = await asyncio.to_thread(tasksync.urgent_threshold, self.taskwarrior)
            else:
                self.notify("taskwarrior's `task` command (2.6 or later) cannot be run: tasks are not synced.")
        return self.available
