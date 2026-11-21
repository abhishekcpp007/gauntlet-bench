"""Runs (`3`): every loaded run.

The shipped calibration results per dataset, and each run folder given with `--run`, in one
table: size, the three trust numbers (oracle resolved, the no-op's reward, the best cheat
reward), cheating verdicts, violations and when it ran. `/` filters, `s` sorts, `c` copies the
run id and `enter` opens the run.
"""

from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from .. import format as fmt
from ..cells import run_detail, run_oracle, run_violations
from ..models import RunSummary
from ..theme import Look
from ..widgets.filterbar import FilterBar
from ..widgets.grid import Column, DataGrid
from ..widgets.states import Empty
from .base import DataScreen

INTRO = "A run is a batch of graded episodes. Add yours: gauntlet tui --run <folder>"
NO_RUNS = Empty(
    "No runs loaded.",
    "Add one with gauntlet tui --run <folder>: the folder gauntlet run or gauntlet calibrate wrote.",
)
NO_MATCH = Empty("No runs match.", "Press / and then esc to clear the filter.")
KINDS = {"shipped": "shipped", "folder": "folder"}


def _kind(run: RunSummary, _look: Look) -> Text:
    return Text(KINDS.get(run.kind, run.kind), end="")


def _ran(run: RunSummary, _look: Look) -> Text:
    return Text(fmt.date(run.ran_to or run.ran_from), end="")


COLUMNS: tuple[Column[RunSummary], ...] = (
    Column("id", "Run", lambda r: r.id, kind="id", shrink=True),
    Column("title", "Title", lambda r: r.title, priority=7),
    Column("kind", "Kind", lambda r: r.kind, render=_kind, priority=4),
    Column("detail", "Detail", lambda r: r.detail, render=run_detail, priority=4),
    Column("episodes", "Episodes", lambda r: r.episodes, kind="number"),
    Column("tasks", "Tasks", lambda r: r.tasks, kind="number", priority=3),
    Column("policies", "Policies", lambda r: len(r.policies), kind="number", priority=5),
    Column(
        "oracle", "Oracle", lambda r: r.oracle.resolved if r.oracle else None, render=run_oracle, priority=2
    ),
    Column("noop", "No-op", lambda r: r.noop.max_reward if r.noop else None, kind="reward", priority=3),
    Column(
        "cheat", "Best cheat", lambda r: r.cheats.max_reward if r.cheats else None, kind="reward", priority=2
    ),
    Column(
        "cheating",
        "Cheating",
        lambda r: r.cheats.cheating_verdicts if r.cheats else None,
        kind="number",
        priority=5,
    ),
    Column("violations", "Violations", lambda r: r.violations, render=run_violations),
    Column("ran", "Ran", lambda r: r.ran_to or r.ran_from, render=_ran, priority=3),
)


def matches(run: RunSummary, query: str) -> bool:
    """Whether `query` appears in the run's id, title, kind, dataset or path."""
    needle = query.strip().lower()
    haystack = (run.id, run.title, KINDS.get(run.kind, run.kind), run.dataset_id or "", run.path or "")
    return not needle or any(needle in value.lower() for value in haystack)


class RunsScreen(DataScreen[tuple[RunSummary, ...]]):
    CSS_PATH = "runs.tcss"
    crumb = "Runs"
    what = "runs"

    def __init__(self) -> None:
        super().__init__()
        self.runs: tuple[RunSummary, ...] = ()

    def fetch(self) -> tuple[RunSummary, ...]:
        return self.source.runs()

    def build(self, data: tuple[RunSummary, ...]) -> Iterable[Widget]:
        self.runs = data
        yield Static(INTRO, markup=False, classes="intro", id="runs-intro")
        grid: DataGrid[RunSummary] = DataGrid(
            COLUMNS, key=lambda r: r.id, empty=NO_RUNS, what="run id", id="runs"
        )
        grid.set_rows(data)
        pane = Vertical(FilterBar(placeholder="type to filter runs"), grid, id="runs-pane", classes="pane")
        pane.border_title = f"Runs {self.gauntlet.look.glyphs.dot} {len(data)}"
        yield pane

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        shown = [r for r in self.runs if matches(r, event.query)]
        grid: DataGrid[RunSummary] = self.query_one("#runs", DataGrid)
        grid.set_rows(shown, empty=NO_MATCH if self.runs else NO_RUNS)
        event.bar.set_count(len(shown), len(self.runs))

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.gauntlet.open_run(event.key)

    def copy_target(self) -> tuple[str, str] | None:
        grids = self.query("#runs")
        key = grids.first(DataGrid).current_key if grids else None
        return None if key is None else (key, "run id")
