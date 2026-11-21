"""Dataset: one task set.

Its numbers, the funnel from PRs collected to tasks kept, tasks by repo as a bar chart, and its
tasks in the same table as the Tasks screen, where `enter` opens a task.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Static

from .. import format as fmt
from ..models import DatasetDetail, TaskRow
from ..theme import leak_mark
from ..widgets.filterbar import FacetGroup
from ..widgets.grid import DataGrid
from ..widgets.stat import Stat
from ..widgets.states import Empty
from ..widgets.themed import Themed
from .base import DataScreen
from .tasks import TaskTable

BAR_GAP = 2
MIN_BAR = 4
MIN_LABEL = 8
SCROLLBAR_WIDTH = 1
FRAME_ROWS = 2
NO_FUNNEL_ROWS = 3
SOLID = ("█", "#")
GHOST = ("░", ".")

NO_FUNNEL = (
    "No funnel for this set. It shipped without a stats.json, so how many PRs were collected "
    "and dropped at each stage isn't known."
)
NO_TASKS = Empty("This set has no tasks.", "Its tasks.jsonl is empty.")


@dataclass(frozen=True, slots=True)
class Bar:
    """One row of a bar chart: `filled` solid cells' worth, then `ghost` light ones, on a shared
    scale. `note` sits muted before the value, like the PRs a stage dropped."""

    label: str
    value: int
    filled: int
    ghost: int = 0
    note: str = ""


class Bars(Themed):
    """An aligned text bar chart: label, note, value, then the bar, which takes the rest of the width."""

    DEFAULT_CSS = """
    Bars {
        height: auto;
    }
    """

    def __init__(self, bars: Sequence[Bar], *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.bars = tuple(bars)

    def render(self) -> RenderableType:
        look = self.look
        solid, ghost = (SOLID[1], GHOST[1]) if look.ascii else (SOLID[0], GHOST[0])
        values = [fmt.count(bar.value) for bar in self.bars]
        note_width = max((cell_len(bar.note) for bar in self.bars), default=0)
        value_width = max((cell_len(v) for v in values), default=0)
        fixed = [value_width] + ([note_width] if note_width else [])
        width = self.size.width - SCROLLBAR_WIDTH
        widest = max((cell_len(bar.label) for bar in self.bars), default=0)
        label_width = max(min(widest, width - sum(fixed) - BAR_GAP * (len(fixed) + 1) - MIN_BAR), MIN_LABEL)
        room = max(width - label_width - sum(fixed) - BAR_GAP * (len(fixed) + 1), MIN_BAR)
        scale = max((bar.filled + bar.ghost for bar in self.bars), default=0) or 1
        grid = Table.grid(padding=(0, BAR_GAP))
        grid.add_column(no_wrap=True)
        if note_width:
            grid.add_column(justify="right", no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column(no_wrap=True)
        for bar, value in zip(self.bars, values, strict=True):
            cells = round(room * bar.filled / scale)
            light = round(room * (bar.filled + bar.ghost) / scale) - cells
            drawn = look.accent(solid * cells)
            drawn.append_text(look.muted(ghost * light))
            label = fmt.middle(bar.label, label_width, look.glyphs.ellipsis)
            row: list[RenderableType] = [fmt.safe_text(label, single_line=True)]
            if note_width:
                row.append(look.muted(bar.note))
            row += [Text(value, end=""), drawn]
            grid.add_row(*row)
        return grid


def funnel(detail: DatasetDetail) -> list[Bar]:
    """PRs collected, what each stage dropped and what was left after it, then the tasks kept."""
    if detail.prs_collected is None:
        return []
    left = detail.prs_collected
    bars = [Bar("PRs collected", left, left)]
    for stage in detail.rejected_by_stage:
        left -= stage.count
        bars.append(Bar(stage.id, left, left, ghost=stage.count, note=f"-{fmt.count(stage.count)}"))
    bars.append(Bar("Tasks kept", detail.summary.tasks, detail.summary.tasks))
    return bars


def headline(detail: DatasetDetail, look_ok: Text) -> list[Stat]:
    summary = detail.summary
    return [
        Stat(fmt.count(summary.tasks), "tasks"),
        Stat(fmt.count(summary.repos), "repos"),
        Stat(look_ok, "leak checks"),
        Stat(fmt.count(summary.f2p_total), "F2P"),
        Stat(fmt.count(summary.n2p_total), "N2P"),
        Stat(fmt.count(summary.s2p_total), "S2P"),
        Stat(fmt.count(summary.p2p_total), "P2P"),
    ]


class DatasetScreen(DataScreen[tuple[DatasetDetail, tuple[TaskRow, ...]]]):
    CSS_PATH = ["dataset.tcss", "tasks.tcss"]

    what = "the dataset"

    def __init__(self, dataset_id: str) -> None:
        super().__init__()
        self.dataset_id = dataset_id
        self.crumb = dataset_id

    def fetch(self) -> tuple[DatasetDetail, tuple[TaskRow, ...]]:
        return self.source.dataset(self.dataset_id), self.source.tasks(dataset=self.dataset_id)

    def build(self, data: tuple[DatasetDetail, tuple[TaskRow, ...]]) -> Iterable[Widget]:
        detail, rows = data
        summary = detail.summary
        look = self.gauntlet.look
        dot = f" {look.glyphs.dot} "
        ok = look.mark(leak_mark(summary.leakcheck_ok == summary.tasks), word=False)
        ok.append(f" {fmt.ratio(summary.leakcheck_ok, summary.tasks)}")
        yield Horizontal(*headline(detail, ok), id="dataset-headline")
        about = [summary.title, f"merged {fmt.date_range(summary.merged_from, summary.merged_to)}"]
        about += [f"{f.id} {fmt.count(f.count)}" for f in summary.runners]
        yield Static(look.muted(dot.join(about)), id="dataset-about")
        bars = funnel(detail)
        if bars:
            funnel_body: Widget = Bars(bars, id="funnel")
            kept = f"{fmt.plural(bars[0].value, 'PR')} to {fmt.plural(summary.tasks, 'task')}"
            funnel_title = f"Funnel{dot}{kept}"
        else:
            funnel_body = Static(Text(NO_FUNNEL), id="no-funnel", classes="intro")
            funnel_title = "Funnel"
        repos = Bars([Bar(f.id, f.count, f.count) for f in detail.by_repo], id="by-repo")
        charts = Horizontal(
            self.pane(funnel_title, VerticalScroll(funnel_body), id="funnel-pane"),
            self.pane(f"Tasks by repo{dot}{fmt.count(summary.repos)}", VerticalScroll(repos), id="repo-pane"),
            id="dataset-charts",
        )
        charts.styles.height = max(len(bars) or NO_FUNNEL_ROWS, len(detail.by_repo)) + FRAME_ROWS
        yield charts
        groups = [
            FacetGroup("repo", "Repo", detail.by_repo),
            FacetGroup("category", "Category", summary.categories),
            FacetGroup("runner", "Runner", summary.runners),
        ]
        scope = {"dataset": self.dataset_id}
        yield TaskTable(rows, groups, scope=scope, empty=NO_TASKS, focus=True, id="dataset-tasks")

    @staticmethod
    def pane(title: str, body: Widget, *, id: str) -> Vertical:
        pane = Vertical(body, id=id, classes="pane chart")
        pane.border_title = title
        return pane

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.gauntlet.open_task(event.key)

    def copy_target(self) -> tuple[str, str] | None:
        return self.dataset_id, "dataset id"
