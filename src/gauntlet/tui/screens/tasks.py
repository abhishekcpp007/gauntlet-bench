"""Tasks (`2`): every task in one table.

Instance, dataset, repo, category, runner, merged date, F2P, N2P, P2P and the leak check. `/`
searches ids, repos and PR titles as you type, `f` narrows by dataset, repo, category or runner,
`s` cycles the sort, and `enter` opens the task. `TaskTable` is the table with its filter bar, and
the Dataset screen uses it too.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import partial
from typing import TYPE_CHECKING, ClassVar, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical
from textual.widget import Widget
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..models import TaskFacets, TaskRow
from ..theme import leak_mark, look_for
from ..widgets.filterbar import FacetGroup, FilterBar
from ..widgets.grid import Column, DataGrid
from ..widgets.states import Empty, describe_error
from ..workbench.base import shortcut
from .base import DataScreen

if TYPE_CHECKING:
    from .base import GauntletScreen

FILTER_GROUP = "task-filter"
PLACEHOLDER = "type to filter tasks"

COLUMNS: tuple[Column[TaskRow], ...] = (
    Column("id", "Instance", lambda t: t.instance_id, kind="id", shrink=True),
    Column("dataset", "Dataset", lambda t: t.dataset_id, priority=4),
    Column("repo", "Repo", lambda t: t.repo),
    Column("category", "Kind", lambda t: t.category, priority=3),
    Column("runner", "Runner", lambda t: t.runner, priority=5),
    Column("merged", "Merged", lambda t: t.merged_at, kind="date", priority=2),
    Column("f2p", "F2P", lambda t: t.f2p, kind="number"),
    Column("n2p", "N2P", lambda t: t.n2p, kind="number", priority=2),
    Column("p2p", "P2P", lambda t: t.p2p, kind="number", priority=2),
    Column("leak", "Leak check", lambda t: leak_mark(t.leakcheck_ok), kind="mark"),
)

NO_TASKS = Empty(
    "No tasks loaded.", "Pass --datasets DIR, or start from a folder that has a datasets/ folder in it."
)
NO_MATCH = Empty("No task matches.", "Press esc in the filter to clear it, or f to change the facets.")


def facet_groups(facets: TaskFacets) -> tuple[FacetGroup, ...]:
    return (
        FacetGroup("dataset", "Dataset", facets.datasets),
        FacetGroup("repo", "Repo", facets.repos),
        FacetGroup("category", "Category", facets.categories),
        FacetGroup("runner", "Runner", facets.runners),
    )


class TaskTable(Vertical):
    """A pane with the `/` filter bar over the task table. Filters re-query the `DataSource`
    off the UI thread. `scope` holds filters that never change, like the Dataset screen's set."""

    def __init__(
        self,
        rows: Sequence[TaskRow],
        groups: Sequence[FacetGroup],
        *,
        title: str = "Tasks",
        scope: Mapping[str, str] | None = None,
        empty: Empty = NO_TASKS,
        focus: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id, classes="pane task-table")
        self.rows = tuple(rows)
        self.total = len(self.rows)
        self.groups = tuple(groups)
        self.scope = dict(scope or {})
        self.empty = empty
        self.title = title
        self.focus_first = focus

    def compose(self) -> ComposeResult:
        yield FilterBar(self.groups, placeholder=PLACEHOLDER)
        grid: DataGrid[TaskRow] = DataGrid(
            COLUMNS, key=lambda t: t.instance_id, empty=self.empty, what="instance id"
        )
        grid.set_rows(self.rows)
        yield grid

    @property
    def grid(self) -> DataGrid[TaskRow]:
        return cast("DataGrid[TaskRow]", self.query_one(DataGrid))

    @property
    def bar(self) -> FilterBar:
        return self.query_one(FilterBar)

    def on_mount(self) -> None:
        self.border_title = f"{self.title} {look_for(self).glyphs.dot} {fmt.count(self.total)}"
        self.bar.set_groups(self.groups)
        self.bar.set_count(self.total, self.total)
        if self.focus_first:
            self.grid.focus_table()

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        event.stop()
        screen = cast("GauntletScreen", self.screen)
        query = partial(screen.source.tasks, **{**event.facets, **self.scope}, query=event.query)
        self.run_worker(query, thread=True, exclusive=True, group=FILTER_GROUP, exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != FILTER_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS:
            rows = cast("tuple[TaskRow, ...]", event.worker.result)
            self.grid.set_rows(rows, empty=NO_MATCH if self.total else self.empty)
            self.bar.set_count(len(rows), self.total)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            failed = Empty("Couldn't filter the tasks.", describe_error(event.worker.error))
            self.grid.set_rows((), empty=failed)
            self.bar.set_count(0, self.total)


class TasksScreen(DataScreen[tuple[tuple[TaskRow, ...], TaskFacets]]):
    CSS_PATH = "tasks.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [Binding(*shortcut("make_tasks"), "Make tasks")]

    crumb = "Tasks"
    what = "tasks"

    def fetch(self) -> tuple[tuple[TaskRow, ...], TaskFacets]:
        return self.source.tasks(), self.source.task_facets()

    def build(self, data: tuple[tuple[TaskRow, ...], TaskFacets]) -> Iterable[Widget]:
        rows, facets = data
        yield TaskTable(rows, facet_groups(facets), id="tasks")

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.gauntlet.open_task(event.key)

    def workbench_values(self, action_id: str) -> dict[str, str] | None:
        """Making tasks starts from a repo, so there's nothing to fill in from here."""
        return {}
