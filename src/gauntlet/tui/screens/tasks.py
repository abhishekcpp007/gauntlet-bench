"""Tasks (`2`): every task in one table.

The full screen shows instance, dataset, repo, category, runner, merged date, F2P, N2P, P2P and
the leak check, with `/` to search, `f` for facets and `s` to sort. Today it lists ids and opens
a task with `enter`.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from ..models import TaskRow
from ..widgets.grid import Column, DataGrid
from ..widgets.states import Empty
from .base import DataScreen

COLUMNS: tuple[Column[TaskRow], ...] = (
    Column("id", "Instance", lambda t: t.instance_id, kind="id", shrink=True),
    Column("dataset", "Dataset", lambda t: t.dataset_id, priority=2),
)


class TasksScreen(DataScreen[tuple[TaskRow, ...]]):
    crumb = "Tasks"
    what = "tasks"

    def fetch(self) -> tuple[TaskRow, ...]:
        return self.source.tasks()

    def build(self, data: tuple[TaskRow, ...]) -> Iterable[Widget]:
        grid: DataGrid[TaskRow] = DataGrid(
            COLUMNS, key=lambda t: t.instance_id, empty=Empty("No tasks loaded."), what="instance id"
        )
        grid.set_rows(data)
        yield grid

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.gauntlet.open_task(event.key)
