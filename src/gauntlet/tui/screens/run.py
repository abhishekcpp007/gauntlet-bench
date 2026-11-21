"""Run: one run, from its facts and trust numbers down to every episode.

The facts block says what the run is and where it came from, with the three trust numbers large:
oracle resolved, the no-op's reward and the best cheat reward. Tabs below: Summary (one row per
policy, and per category when a run mixes swe and lht), Matrix (tasks by policies), Episodes
(filterable, `enter` opens one) and Calibration (the check `gauntlet calibrate` makes).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text
from textual import work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Static, TabbedContent, TabPane

from .. import format as fmt
from ..models import (
    EpisodeFacets,
    EpisodeRow,
    PolicyGroup,
    PolicyKind,
    PolicyRow,
    RunDetail,
    RunSummary,
    Thresholds,
)
from ..models import Matrix as MatrixData
from ..theme import (
    ERROR,
    FAILED,
    SUMMARY_ONLY,
    VERDICTS,
    WARNING,
    Look,
    check_mark,
    resolved_mark,
    tamper_mark,
)
from ..widgets.deferred import Deferred
from ..widgets.definitions import Definition, Definitions
from ..widgets.facts import Fact, Facts
from ..widgets.filterbar import FacetGroup, FilterBar
from ..widgets.grid import Column, DataGrid
from ..widgets.matrix import Matrix
from ..widgets.stat import Stat
from ..widgets.states import Empty, EmptyState
from ..widgets.themed import Themed
from .base import DataScreen

KIND_ORDER: dict[PolicyKind, int] = {"oracle": 0, "noop": 1, "cheat": 2, "model": 3}
CATEGORY_ORDER = {"swe": 0, "lht": 1}
PASS_DIGITS = 2
SUMMARY_TAB = "summary"
MATRIX_TAB = "matrix"
EPISODES_TAB = "episodes"
CALIBRATION_TAB = "calibration"
SUMMARY_INTRO = (
    "One row per policy. pass@1 is the share of tasks resolved on the first try, "
    "with its 95% interval. Enter lists its episodes."
)
SUMMARY_ONLY_NOTE = "summary rows only: the full records weren't shipped"
UNCHECKED = (
    "This run only has summary rows, so the calibration check can't be made here. "
    "gauntlet calibrate makes it on a full run folder."
)
CALIBRATION_INTRO = "The same check gauntlet calibrate makes. A run passes when:"
ROTTED_NOTE = "A task whose pinned commit is gone upstream is left out of the check."
NO_EPISODES = Empty("No episodes in this run.")
NO_MATCH = Empty("No episodes match.", "Press / and then esc to clear the search, or f to change facets.")
NO_MATRIX = Empty("Nothing to show.", "This run has no episodes, so there's no matrix.")
FACETS = (("policy", "Policy"), ("verdict", "Verdict"), ("task", "Task"))


@dataclass(frozen=True, slots=True)
class RunData:
    """Everything the run screen shows up front, fetched together in the worker."""

    detail: RunDetail
    thresholds: Thresholds
    episodes: tuple[EpisodeRow, ...]
    facets: EpisodeFacets


def ordered_policies(rows: Iterable[PolicyRow], policies: tuple[str, ...]) -> list[PolicyRow]:
    """Grouped by category, then oracle, noop, cheats and models, each in the run's own order."""
    position = {policy: index for index, policy in enumerate(policies)}
    return sorted(
        rows,
        key=lambda r: (
            CATEGORY_ORDER.get(r.category or "", len(CATEGORY_ORDER)),
            KIND_ORDER[r.kind],
            position.get(r.policy, len(position)),
        ),
    )


def mixed(rows: Iterable[PolicyRow]) -> bool:
    return len({r.category for r in rows}) > 1


def policy_key(row: PolicyRow, *, by_category: bool) -> str:
    return f"{row.policy} ({row.category})" if by_category else row.policy


def pass_at_1(row: PolicyRow, look: Look) -> Text:
    interval = row.pass_at_1
    if interval is None:
        return look.muted(fmt.MISSING)
    text = Text(f"{interval.value:.{PASS_DIGITS}f}", end="")
    text.append_text(look.muted(f" [{interval.low:.{PASS_DIGITS}f}, {interval.high:.{PASS_DIGITS}f}]"))
    return text


def _flagged(value: int | None, look: Look) -> Text:
    if value is None:
        return look.muted(fmt.MISSING)
    return Text(fmt.count(value), style=look.style("bad") if value else look.style("muted"), end="")


def _cheating(row: PolicyRow, look: Look) -> Text:
    return _flagged(row.verdicts.cheating, look)


def _tampered(row: PolicyRow, look: Look) -> Text:
    return _flagged(row.tampered, look)


def _errors(row: PolicyRow, look: Look) -> Text:
    return _flagged(row.errors, look)


def _suspicious(row: PolicyRow, look: Look) -> Text:
    count = row.verdicts.suspicious
    return Text(fmt.count(count), style=look.style("warn") if count else look.style("muted"), end="")


def summary_columns(*, by_category: bool) -> tuple[Column[PolicyRow], ...]:
    columns: list[Column[PolicyRow]] = [
        Column("policy", "Policy", lambda r: r.policy, kind="id", shrink=True),
        Column("kind", "Kind", lambda r: r.kind, priority=6),
        Column("episodes", "Episodes", lambda r: r.episodes, kind="number", priority=4),
        Column("tasks", "Tasks", lambda r: r.tasks, kind="number", priority=7),
        Column("resolved", "Resolved", lambda r: r.resolved, kind="number"),
        Column(
            "pass",
            "pass@1",
            lambda r: r.pass_at_1.value if r.pass_at_1 else None,
            render=pass_at_1,
            priority=2,
        ),
        Column("mean", "Mean", lambda r: r.mean_reward, kind="reward"),
        Column("min", "Min", lambda r: r.min_reward, kind="reward", priority=5),
        Column("max", "Max", lambda r: r.max_reward, kind="reward", priority=3),
        Column("clean", "Clean", lambda r: r.verdicts.clean, kind="number", priority=5),
        Column(
            "suspicious",
            "Suspicious",
            lambda r: r.verdicts.suspicious,
            kind="number",
            render=_suspicious,
            priority=6,
        ),
        Column(
            "cheating", "Cheating", lambda r: r.verdicts.cheating, kind="number", render=_cheating, priority=2
        ),
        Column("tampered", "Tampered", lambda r: r.tampered, kind="number", render=_tampered, priority=3),
        Column("errors", "Errors", lambda r: r.errors, kind="number", render=_errors, priority=4),
    ]
    if by_category:
        columns.insert(1, Column("category", "Set", lambda r: r.category, priority=2))
    return tuple(columns)


def _resolved(row: EpisodeRow, look: Look) -> Text:
    return look.mark(resolved_mark(row.resolved))


def _verdict(row: EpisodeRow, look: Look) -> Text:
    return look.mark(ERROR if row.error else VERDICTS[row.cheat_verdict])


def _episode_tampered(row: EpisodeRow, look: Look) -> Text:
    return look.muted(fmt.MISSING) if row.tampered is None else look.mark(tamper_mark(row.tampered))


def _time(row: EpisodeRow, look: Look) -> Text:
    return look.muted(fmt.MISSING) if row.seconds is None else Text(fmt.duration(row.seconds), end="")


EPISODE_COLUMNS: tuple[Column[EpisodeRow], ...] = (
    Column("task", "Task", lambda e: e.instance_id, kind="id", shrink=True),
    Column("policy", "Policy", lambda e: e.policy, kind="id"),
    Column("reward", "Reward", lambda e: e.reward, kind="reward"),
    Column("resolved", "Resolved", lambda e: e.resolved, render=_resolved, priority=2),
    Column("verdict", "Verdict", lambda e: "error" if e.error else e.cheat_verdict, render=_verdict),
    Column("tampered", "Tampered", lambda e: e.tampered, render=_episode_tampered, priority=3),
    Column("steps", "Steps", lambda e: e.steps, kind="number", priority=4),
    Column("time", "Time", lambda e: e.seconds, render=_time, priority=4),
    Column("error", "Error", lambda e: e.error, priority=3),
)


def _ratio(group: PolicyGroup | None, look: Look) -> Text:
    if group is None:
        return look.muted(fmt.MISSING)
    text = look.mark(check_mark(group.resolved == group.episodes), word=False)
    text.append(f" {fmt.ratio(group.resolved, group.episodes)}")
    return text


def _max(group: PolicyGroup | None, look: Look) -> Text:
    return look.reward(group.max_reward if group else None)


def trust_numbers(summary: RunSummary, look: Look) -> list[Stat]:
    return [
        Stat(_ratio(summary.oracle, look), "oracle resolved"),
        Stat(_max(summary.noop, look), "no-op reward"),
        Stat(_max(summary.cheats, look), "best cheat"),
    ]


def run_facts(summary: RunSummary, look: Look) -> list[Fact]:
    dot = f" {look.glyphs.dot} "
    size = dot.join(
        [
            fmt.plural(summary.episodes, "episode"),
            fmt.plural(summary.tasks, "task"),
            fmt.plural(len(summary.policies), "policy", "policies"),
        ]
    )
    if summary.path:
        source = Fact("Folder", summary.path)
    else:
        source = Fact("Dataset", summary.dataset_id or fmt.MISSING)
    kind = "shipped calibration" if summary.kind == "shipped" else "run folder"
    if summary.detail == "summary":
        detail: str | Text = look.mark(SUMMARY_ONLY, word=False) + Text(f" {SUMMARY_ONLY_NOTE}", end="")
    else:
        detail = "full records"
    ran = fmt.date_range(summary.ran_from, summary.ran_to)
    if summary.ran_from and summary.ran_to:
        ran = f"{fmt.date_time(summary.ran_from)} to {fmt.date_time(summary.ran_to)}"
    return [
        Fact("Run", Text(summary.title, style="bold", end=""), copy=summary.id),
        Fact("Kind", kind),
        source,
        Fact("Size", size),
        Fact("Ran", ran),
        Fact("Detail", detail, copy=summary.detail),
    ]


def rule_rows(thresholds: Thresholds) -> list[Definition]:
    oracle, noop, cheat = (
        fmt.reward(value).strip()
        for value in (thresholds.oracle_min_reward, thresholds.noop_reward, thresholds.cheat_max_reward)
    )
    return [
        Definition("oracle", f"The real fix has to resolve and score at least {oracle}."),
        Definition("noop", f"Doing nothing has to score exactly {noop}."),
        Definition("cheats", f"No cheat may resolve or score above {cheat}."),
    ]


class CalibrationResult(Themed):
    """Whether the run passed the calibration check, each violation on its own line, and any
    rotted tasks that were left out."""

    DEFAULT_CSS = """
    CalibrationResult {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, detail: RunDetail) -> None:
        super().__init__()
        self.detail = detail

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="")
        if not self.detail.violations:
            text.append_text(look.mark(check_mark(True), word=False))
            text.append(" No violations", style=look.style("good", bold=True))
        else:
            count = fmt.plural(len(self.detail.violations), "violation")
            text.append_text(look.mark(WARNING, word=False))
            text.append(f" {count}", style=look.style("warn", bold=True))
            for violation in self.detail.violations:
                text.append("\n")
                text.append_text(look.mark(FAILED, word=False))
                text.append(" ")
                text.append_text(fmt.safe_text(violation, single_line=True))
        if self.detail.rotted:
            text.append("\n\n")
            text.append(f"Rotted {fmt.plural(len(self.detail.rotted), 'task')}", style="bold")
            text.append("\n")
            text.append_text(look.muted(ROTTED_NOTE))
            for task, reason in self.detail.rotted:
                text.append("\n")
                text.append_text(look.mark(WARNING, word=False))
                text.append(" ")
                text.append_text(fmt.safe_text(task, single_line=True, style="bold"))
                text.append_text(look.muted(f"  {fmt.one_line(reason)}"))
        return text


def facet_groups(facets: EpisodeFacets) -> list[FacetGroup]:
    values = {"policy": facets.policies, "verdict": facets.verdicts, "task": facets.tasks}
    return [FacetGroup(key, label, values[key]) for key, label in FACETS]


class RunScreen(DataScreen[RunData]):
    CSS_PATH = "run.tcss"
    what = "the run"

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.crumb = run_id
        self.total_episodes = 0
        self.pending: str | None = None

    def fetch(self) -> RunData:
        source = self.source
        detail = source.run(self.run_id)
        return RunData(
            detail=detail,
            thresholds=source.reference().thresholds,
            episodes=source.episodes(self.run_id),
            facets=source.episode_facets(self.run_id),
        )

    def build(self, data: RunData) -> Iterable[Widget]:
        look = self.gauntlet.look
        summary = data.detail.summary
        self.total_episodes = len(data.episodes)
        yield Horizontal(
            Facts(run_facts(summary, look), id="run-facts"),
            Vertical(*trust_numbers(summary, look), id="run-stats"),
            id="run-top",
        )
        tabs = TabbedContent(id="run-tabs")
        tabs.compose_add_child(TabPane("Summary", *self.summary_tab(data.detail), id=SUMMARY_TAB))
        matrix = Deferred(self.fetch_matrix, self.build_matrix, what="the matrix")
        tabs.compose_add_child(TabPane("Matrix", matrix, id=MATRIX_TAB))
        tabs.compose_add_child(
            TabPane(f"Episodes {fmt.count(len(data.episodes))}", *self.episodes_tab(data), id=EPISODES_TAB)
        )
        tabs.compose_add_child(TabPane("Calibration", self.calibration_tab(data), id=CALIBRATION_TAB))
        yield tabs

    def summary_tab(self, detail: RunDetail) -> Iterable[Widget]:
        by_category = mixed(detail.policies)
        grid: DataGrid[PolicyRow] = DataGrid(
            summary_columns(by_category=by_category),
            key=lambda r: policy_key(r, by_category=by_category),
            empty=Empty("No policies in this run."),
            what="policy",
            id="policies",
        )
        grid.set_rows(ordered_policies(detail.policies, detail.summary.policies))
        yield Static(SUMMARY_INTRO, markup=False, classes="intro")
        yield grid

    def episodes_tab(self, data: RunData) -> Iterable[Widget]:
        groups = facet_groups(data.facets)
        bar = FilterBar(groups, placeholder="type to search episodes", id="episodes-filter")
        grid: DataGrid[EpisodeRow] = DataGrid(
            EPISODE_COLUMNS,
            key=lambda e: e.episode_id,
            empty=NO_EPISODES,
            what="episode id",
            id="episode-grid",
        )
        grid.set_rows(data.episodes)
        yield bar
        yield grid

    def calibration_tab(self, data: RunData) -> Widget:
        if not data.detail.calibration_checked:
            return VerticalScroll(Static(UNCHECKED, markup=False, classes="intro"), id="calibration-body")
        intro = Static(CALIBRATION_INTRO, markup=False, classes="intro")
        return VerticalScroll(
            intro,
            Definitions(rule_rows(data.thresholds)),
            CalibrationResult(data.detail),
            id="calibration-body",
        )

    def fetch_matrix(self) -> MatrixData:
        return self.source.matrix(self.run_id)

    def build_matrix(self, data: MatrixData) -> Iterable[Widget]:
        if not data.tasks:
            yield EmptyState(NO_MATRIX)
            return
        matrix = Matrix(data)
        yield matrix
        self.call_after_refresh(self.focus_pane, self.query_one(f"#{MATRIX_TAB}", TabPane))

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        self.requery(event.query, event.facets)

    @work(thread=True, exclusive=True, group="episodes", exit_on_error=False)
    def requery(self, query: str, facets: Mapping[str, str]) -> None:
        try:
            rows = self.source.episodes(
                self.run_id,
                policy=facets.get("policy"),
                task=facets.get("task"),
                verdict=facets.get("verdict"),
                query=query,
            )
        except Exception as error:  # a failed search keeps the old rows and says why
            self.app.call_from_thread(self.notify, f"Search failed: {error}", severity="error", markup=False)
            return
        self.app.call_from_thread(self.show_episodes, rows)

    def show_episodes(self, rows: tuple[EpisodeRow, ...]) -> None:
        grid: DataGrid[EpisodeRow] = self.query_one("#episode-grid", DataGrid)
        grid.set_rows(rows, empty=NO_MATCH if self.total_episodes else NO_EPISODES)
        self.query_one("#episodes-filter", FilterBar).set_count(len(rows), self.total_episodes)

    def show_tab(self, tab: str) -> None:
        self.query_one("#run-tabs", TabbedContent).active = tab

    def action_filter(self) -> None:
        self.on_episodes("filter")

    def action_facets(self) -> None:
        self.on_episodes("facets")

    def on_episodes(self, action: str) -> None:
        """Run the base `/` or `f` on the Episodes tab, switching to it first if needed."""
        tabs = self.query("#run-tabs")
        if not tabs:
            return
        if tabs.first(TabbedContent).active == EPISODES_TAB:
            self.base_action(action)
        else:
            self.pending = action
            self.show_tab(EPISODES_TAB)

    def base_action(self, action: str) -> None:
        if action == "filter":
            super().action_filter()
        else:
            super().action_facets()

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        if event.grid.id == "episode-grid":
            self.gauntlet.open_episode(self.run_id, event.key)
        elif event.grid.id == "policies" and isinstance(event.row, PolicyRow):
            self.show_tab(EPISODES_TAB)
            self.query_one("#episodes-filter", FilterBar).set_facet("policy", event.row.policy)
            self.query_one("#episode-grid", DataGrid).focus_table()

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        action, self.pending = self.pending, None
        if action is not None:
            self.call_after_refresh(self.base_action, action)
        else:
            self.call_after_refresh(self.focus_pane, event.pane)

    def focus_pane(self, pane: Widget) -> None:
        """Move focus into `pane`, unless it's already there."""
        focused = self.focused
        if focused is not None and pane in focused.ancestors_with_self:
            return
        for widget in pane.query("*"):
            if widget.focusable and not isinstance(widget, Input):
                widget.focus()
                return

    def on_matrix_opened(self, event: Matrix.Opened) -> None:
        self.gauntlet.open_episode(self.run_id, event.episode_id)

    def copy_target(self) -> tuple[str, str] | None:
        return self.run_id, "run id"
