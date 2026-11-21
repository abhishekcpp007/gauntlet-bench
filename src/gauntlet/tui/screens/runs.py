"""Runs (`3`): every loaded run.

The full screen lists the shipped calibration results per dataset and each run folder from the
command line, with episodes, tasks, policies, oracle resolved, best cheat reward and violations.
Today it lists run ids and episode counts and opens a run with `enter`.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from ..models import RunSummary
from ..widgets.grid import Column, DataGrid
from ..widgets.states import Empty
from .base import DataScreen

COLUMNS: tuple[Column[RunSummary], ...] = (
    Column("id", "Run", lambda r: r.id, kind="id", shrink=True),
    Column("episodes", "Episodes", lambda r: r.episodes, kind="number"),
)


class RunsScreen(DataScreen[tuple[RunSummary, ...]]):
    crumb = "Runs"
    what = "runs"

    def fetch(self) -> tuple[RunSummary, ...]:
        return self.source.runs()

    def build(self, data: tuple[RunSummary, ...]) -> Iterable[Widget]:
        grid: DataGrid[RunSummary] = DataGrid(
            COLUMNS, key=lambda r: r.id, empty=Empty("No runs loaded."), what="run id"
        )
        grid.set_rows(data)
        yield grid

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.gauntlet.open_run(event.key)
