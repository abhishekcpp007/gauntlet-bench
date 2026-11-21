"""Overview (`1`): what's loaded, at a glance.

Headline numbers, a table of datasets and a table of runs (both open with `enter`), and the
"How a score is made" strip that walks the grading steps in order.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from rich.console import RenderableType
from rich.text import Text
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from .. import format as fmt
from ..cells import run_detail, run_oracle, run_violations
from ..models import DatasetSummary, Overview, Reference, ReferenceItem, RunSummary
from ..theme import WARNING, Look, check_mark, leak_mark
from ..widgets.grid import Column, DataGrid
from ..widgets.stat import Stat
from ..widgets.states import Empty
from ..widgets.themed import Themed
from .base import DataScreen

NO_DATASETS = Empty(
    "No datasets loaded.",
    "Pass --datasets DIR, or start from a folder that has a datasets/ folder in it.",
)
NO_RUNS = Empty(
    "No runs loaded.",
    "Add one with --run DIR: the folder gauntlet run or gauntlet calibrate wrote.",
)


def _runners(summary: DatasetSummary, look: Look) -> Text:
    return Text(f" {look.glyphs.dot} ".join(f"{f.id} {f.count}" for f in summary.runners), end="")


def _merged(summary: DatasetSummary, _look: Look) -> Text:
    return Text(fmt.date_range(summary.merged_from, summary.merged_to), end="")


def _leak(summary: DatasetSummary, look: Look) -> Text:
    text = look.mark(leak_mark(summary.leakcheck_ok == summary.tasks), word=False)
    text.append(f" {fmt.ratio(summary.leakcheck_ok, summary.tasks)}")
    return text


DATASET_COLUMNS: tuple[Column[DatasetSummary], ...] = (
    Column("id", "Dataset", lambda d: d.id, kind="id", shrink=True),
    Column("title", "Title", lambda d: d.title, priority=4),
    Column("tasks", "Tasks", lambda d: d.tasks, kind="number"),
    Column("repos", "Repos", lambda d: d.repos, kind="number", priority=3),
    Column(
        "runners", "Runners", lambda d: d.runners[0].id if d.runners else None, render=_runners, priority=5
    ),
    Column("merged", "Merged", lambda d: d.merged_to, render=_merged, priority=4),
    Column("f2p", "F2P", lambda d: d.f2p_total, kind="number", priority=6),
    Column("p2p", "P2P", lambda d: d.p2p_total, kind="number", priority=6),
    Column("leak", "Leak checks", lambda d: d.leakcheck_ok, render=_leak, priority=2),
)

RUN_COLUMNS: tuple[Column[RunSummary], ...] = (
    Column("id", "Run", lambda r: r.id, kind="id", shrink=True),
    Column("kind", "Kind", lambda r: r.kind, priority=5),
    Column("detail", "Detail", lambda r: r.detail, render=run_detail, priority=4),
    Column("episodes", "Episodes", lambda r: r.episodes, kind="number"),
    Column("tasks", "Tasks", lambda r: r.tasks, kind="number", priority=3),
    Column("policies", "Policies", lambda r: len(r.policies), kind="number", priority=5),
    Column(
        "oracle",
        "Oracle resolved",
        lambda r: r.oracle.resolved if r.oracle else None,
        render=run_oracle,
        priority=2,
    ),
    Column(
        "cheat", "Best cheat", lambda r: r.cheats.max_reward if r.cheats else None, kind="reward", priority=2
    ),
    Column("violations", "Violations", lambda r: r.violations, render=run_violations),
)


class ScoreStrip(Themed):
    """The grading steps in order, on as many lines as the width needs."""

    def __init__(self, steps: Sequence[ReferenceItem]) -> None:
        super().__init__()
        self.steps = tuple(steps)

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="")
        for index, step in enumerate(self.steps, start=1):
            if index > 1:
                text.append_text(look.muted(f" {look.glyphs.step} "))
            text.append_text(look.muted(f"{index} "))
            text.append(step.title)
        return text


def headline(overview: Overview, look: Look) -> list[Stat]:
    totals = overview.totals
    checks = totals.tasks * totals.leak_checks_per_task
    passing = checks - totals.leak_check_failures
    oracle = [r.oracle for r in overview.runs if r.oracle is not None]
    cheats = [r.cheats.max_reward for r in overview.runs if r.cheats is not None]
    checked = [r.violations for r in overview.runs if r.violations is not None]
    leak = look.mark(leak_mark(totals.leak_check_failures == 0), word=False) + Text(
        f" {fmt.ratio(passing, checks)}"
    )
    stats = [
        Stat(fmt.count(totals.tasks), "tasks"),
        Stat(fmt.count(totals.repos), "repos"),
        Stat(leak, "leak checks"),
    ]
    if oracle:
        resolved, episodes = sum(g.resolved for g in oracle), sum(g.episodes for g in oracle)
        mark = look.mark(check_mark(resolved == episodes), word=False)
        stats.append(Stat(mark + Text(f" {fmt.ratio(resolved, episodes)}"), "oracle resolved"))
    if cheats:
        stats.append(Stat(look.reward(max(cheats)), "best cheat"))
    if checked:
        bad = sum(checked)
        mark = look.mark(check_mark(True) if bad == 0 else WARNING, word=False)
        stats.append(Stat(mark + Text(f" {fmt.count(bad)}"), "violations"))
    return stats


class OverviewScreen(DataScreen[tuple[Overview, Reference]]):
    crumb = "Overview"
    what = "the overview"

    def fetch(self) -> tuple[Overview, Reference]:
        return self.source.overview(), self.source.reference()

    def build(self, data: tuple[Overview, Reference]) -> Iterable[Widget]:
        overview, reference = data
        look = self.gauntlet.look
        yield Horizontal(*headline(overview, look), id="headline")
        for warning in overview.warnings:
            line = look.mark(WARNING, word=False) + Text(" ") + fmt.safe_text(warning, single_line=True)
            yield Static(line, classes="warning")
        datasets: DataGrid[DatasetSummary] = DataGrid(
            DATASET_COLUMNS, key=lambda d: d.id, empty=NO_DATASETS, what="dataset id", id="datasets"
        )
        datasets.set_rows(overview.datasets)
        runs: DataGrid[RunSummary] = DataGrid(
            RUN_COLUMNS, key=lambda r: r.id, empty=NO_RUNS, what="run id", id="runs"
        )
        runs.set_rows(overview.runs)
        yield self.pane(f"Datasets {look.glyphs.dot} {len(overview.datasets)}", datasets, id="datasets-pane")
        yield self.pane(f"Runs {look.glyphs.dot} {len(overview.runs)}", runs, id="runs-pane")
        strip = Vertical(ScoreStrip(reference.grading_steps), id="score-pane", classes="pane")
        strip.border_title = "How a score is made"
        strip.border_subtitle = "press 4 for the detail"
        yield strip

    @staticmethod
    def pane(title: str, grid: DataGrid, *, id: str) -> Vertical:
        pane = Vertical(grid, id=id, classes="pane")
        pane.border_title = title
        return pane

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        if event.grid.id == "datasets":
            self.gauntlet.open_dataset(event.key)
        elif event.grid.id == "runs":
            self.gauntlet.open_run(event.key)
