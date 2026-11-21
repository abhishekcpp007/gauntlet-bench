"""Task: one task in full.

Facts on top (repo, PR, merged date, category, runner, image, fingerprint, commits), then tabs:
the statement, the tests with their classes and validation runs, the leak check, the patches an
agent never sees, every loaded episode on the task, and the release range on LHT tasks.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from functools import partial
from typing import cast

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widget import Widget
from textual.widgets import Input, Static, TabbedContent, TabPane
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..models import Counts, EpisodeRow, HorizonDetail, TaskDetail, TestClass, ValidationRuns
from ..theme import ERROR, LEAK_FAILED, SUMMARY_ONLY, VERDICTS, WARNING, Look, resolved_mark
from ..widgets.checklist import CheckItem, Checklist
from ..widgets.deferred import Deferred
from ..widgets.definitions import Definition, Definitions
from ..widgets.diff import DiffView
from ..widgets.facts import Fact, Facts
from ..widgets.filterbar import FilterBar
from ..widgets.grid import CELL_PADDING, Column, DataGrid, GridTable
from ..widgets.states import Empty, EmptyState, describe_error
from ..widgets.themed import Themed
from .base import DataScreen

TESTS_TAB = "tests"
P2P_GROUP = "p2p-filter"
COLUMN_GAP = 2
COUNT_COLUMNS = ("passed", "failed", "skipped")

TEST_CLASSES: tuple[tuple[TestClass, str, str], ...] = (
    ("f2p", "fail to pass", "tests the fix makes pass"),
    ("n2p", "new to pass", "tests that didn't exist before"),
    ("s2p", "skipped to pass", "tests that were skipped before and pass with the fix"),
    ("p2p", "pass to pass", "tests that passed before and must keep passing"),
)

STATEMENT_SOURCES = {"issue": "the linked GitHub issue", "pr": "the PR body"}

TESTS_INTRO = (
    "The grader runs four classes of tests. "
    "The agent has to make the first three pass without breaking the fourth."
)
LEAK_INTRO = (
    "A leak check asks whether the agent's sandbox can see the answer anywhere. "
    "A task ships only when every check passes."
)
PATCH_INTRO = (
    "An agent never sees either of these. The fix is what the PR merged, and the hidden tests "
    "go in only after the agent stops, when the grader runs."
)
PATCH_CUT = "cut short: only the start is shown"
HORIZON_INTRO = (
    "This task spans a release range. The agent has to make every change between the two tags, "
    "and the grader checks each milestone on the way."
)

NO_EPISODES = Empty(
    "No loaded run includes this task.",
    "Add a run with --run DIR: the folder gauntlet run or gauntlet calibrate wrote.",
)
NO_P2P = Empty("No pass to pass tests.", "Nothing else in the suite had to keep passing.")
NO_P2P_MATCH = Empty("No test matches.", "Press esc in the filter to clear it.")


def _verdict(row: EpisodeRow, look: Look) -> Text:
    return look.mark(ERROR if row.error else VERDICTS[row.cheat_verdict])


def _detail(row: EpisodeRow, look: Look) -> Text:
    return look.mark(SUMMARY_ONLY) if row.detail == "summary" else Text("full", end="")


EPISODE_COLUMNS: tuple[Column[EpisodeRow], ...] = (
    Column("run", "Run", lambda e: e.run_id, kind="id", shrink=True),
    Column("policy", "Policy", lambda e: e.policy, kind="id"),
    Column("reward", "Reward", lambda e: e.reward, kind="reward"),
    Column("resolved", "Resolved", lambda e: resolved_mark(e.resolved), kind="mark", priority=2),
    Column("verdict", "Verdict", lambda e: "error" if e.error else e.cheat_verdict, render=_verdict),
    Column("steps", "Steps", lambda e: e.steps, kind="number", priority=3),
    Column("detail", "Detail", lambda e: e.detail, render=_detail, priority=4),
)


def episode_key(row: EpisodeRow) -> str:
    return f"{row.run_id}/{row.episode_id}"


class TestTable(GridTable):
    """A table of test ids: they can be copied, but there's nothing to open."""

    __test__ = False

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "select_cursor":
            return False
        return super().check_action(action, parameters)


class TestGrid(DataGrid[str]):
    __test__ = False

    def compose(self) -> ComposeResult:
        yield TestTable(cursor_type="row", zebra_stripes=False, cell_padding=CELL_PADDING)
        yield EmptyState(self.empty)


class TestClasses(Themed):
    """The four test classes: code, name, count and what each one means."""

    __test__ = False

    DEFAULT_CSS = """
    TestClasses {
        height: auto;
    }
    """

    def __init__(self, counts: dict[TestClass, int]) -> None:
        super().__init__()
        self.counts = counts

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, COLUMN_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column()
        for key, name, what in TEST_CLASSES:
            count = Text(fmt.count(self.counts[key]), end="")
            grid.add_row(look.accent(key.upper(), bold=True), Text(name, end=""), count, look.muted(what))
        return grid


class ValidationTable(Themed):
    """How the task was validated: the base run, the tests-only run and each fix run."""

    DEFAULT_CSS = """
    ValidationTable {
        height: auto;
    }
    """

    def __init__(self, runs: ValidationRuns) -> None:
        super().__init__()
        self.runs = runs

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, COLUMN_GAP))
        grid.add_column(no_wrap=True)
        for _ in COUNT_COLUMNS:
            grid.add_column(justify="right", no_wrap=True)
        grid.add_column()
        rows: list[tuple[str, Counts, str]] = [
            ("Base run", self.runs.run, "the repo before the PR"),
            ("Tests only", self.runs.test, "hidden tests in, no fix"),
        ]
        rows += [(f"Fix run {i}", counts, "fix and tests") for i, counts in enumerate(self.runs.fix, start=1)]
        grid.add_row(Text(""), *(look.muted(name) for name in COUNT_COLUMNS), Text(""))
        for label, counts, what in rows:
            numbers = (counts.passed, counts.failed, counts.skipped)
            grid.add_row(Text(label), *(Text(fmt.count(n)) for n in numbers), look.muted(what))
        return grid


class IdList(Themed):
    """A heading with a count, then one id per line, or a muted note when there are none."""

    DEFAULT_CSS = """
    IdList {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(
        self,
        title: str,
        ids: Sequence[str],
        *,
        count: int | None = None,
        note: str = "",
        none: str = "none",
    ) -> None:
        super().__init__()
        self.title = title
        self.ids = tuple(ids)
        self.count = len(self.ids) if count is None else count
        self.note = note
        self.none = none

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="")
        text.append(self.title, style="bold")
        text.append_text(look.muted(f" {look.glyphs.dot} {fmt.count(self.count)}"))
        if self.note:
            text.append_text(look.muted(f"  {self.note}"))
        if not self.ids:
            if self.none:
                text.append("\n")
                text.append_text(look.muted(self.none))
            return text
        rows = Table.grid(padding=(0, 1))
        rows.add_column(no_wrap=True)
        rows.add_column()
        for test in self.ids:
            rows.add_row(look.muted(look.glyphs.bullet), fmt.safe_text(test, single_line=True))
        return Group(text, rows)


class Heading(Themed):
    """A bold title with a muted note after it."""

    DEFAULT_CSS = """
    Heading {
        height: auto;
        margin-top: 1;
    }
    """

    def __init__(self, title: str, note: str = "") -> None:
        super().__init__()
        self.title = title
        self.note = note

    def render(self) -> RenderableType:
        text = Text(end="")
        text.append(self.title, style="bold")
        if self.note:
            text.append_text(self.look.muted(f"  {self.note}"))
        return text


class PassToPass(Vertical):
    """The P2P list with its own `/` search. It can hold thousands of ids, so it re-queries the
    source off the UI thread as you type."""

    def __init__(self, instance_id: str, tests: Sequence[str]) -> None:
        super().__init__(id="p2p")
        self.instance_id = instance_id
        self.tests = tuple(tests)

    def compose(self) -> ComposeResult:
        yield FilterBar(placeholder="filter the test ids")
        widest = max((len(t) for t in self.tests), default=0)
        column = Column("id", "Test", lambda t: t, kind="id", width=widest, shrink=True)
        grid = TestGrid([column], key=lambda t: t, empty=NO_P2P, what="test id", id="p2p-grid")
        grid.set_rows(self.tests)
        yield grid

    def on_mount(self) -> None:
        self.query_one(FilterBar).set_count(len(self.tests), len(self.tests))

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        event.stop()
        screen = cast("TaskScreen", self.screen)
        query = partial(screen.source.task_tests, self.instance_id, "p2p", query=event.query)
        self.run_worker(query, thread=True, exclusive=True, group=P2P_GROUP, exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != P2P_GROUP:
            return
        event.stop()
        grid = self.query_one(TestGrid)
        if event.state == WorkerState.SUCCESS:
            rows = cast("tuple[str, ...]", event.worker.result)
            grid.set_rows(rows, empty=NO_P2P_MATCH if self.tests else NO_P2P)
            self.query_one(FilterBar).set_count(len(rows), len(self.tests))
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            grid.set_rows((), empty=Empty("Couldn't search the tests.", describe_error(event.worker.error)))


def _intro(text: str) -> Static:
    return Static(Text(text), classes="intro")


def _pane(title: str, *children: Widget, id: str | None = None, classes: str = "") -> Vertical:
    pane = Vertical(*children, id=id, classes=f"pane {classes}".strip())
    pane.border_title = title
    return pane


def _titled(title: str, rows: Sequence[Definition]) -> list[Widget]:
    """A heading with a count over a `Definitions` block, or the heading and "none"."""
    if not rows:
        return [IdList(title, ())]
    return [IdList(title, (), count=len(rows), none=""), Definitions(rows)]


class TaskScreen(DataScreen[TaskDetail]):
    CSS_PATH = "task.tcss"

    what = "the task"

    def __init__(self, instance_id: str) -> None:
        super().__init__()
        self.instance_id = instance_id
        self.crumb = instance_id

    def fetch(self) -> TaskDetail:
        return self.source.task(self.instance_id)

    def build(self, data: TaskDetail) -> Iterable[Widget]:
        yield Horizontal(*self.facts(data), id="task-facts")
        row = data.row
        checks_ok = sum(c.ok for c in data.leakchecks)
        tests = fmt.count(row.f2p + row.n2p + row.s2p + row.p2p)
        panes = [
            TabPane("Statement", self.statement(data), id="statement"),
            TabPane(f"Tests {tests}", *self.tests(data), id=TESTS_TAB),
            TabPane(f"Leak check {fmt.ratio(checks_ok, len(data.leakchecks))}", self.leaks(data), id="leaks"),
            TabPane("Patches", Deferred(lambda: data, self.patches, what="the patches"), id="patches"),
            TabPane(f"Episodes {len(data.episodes)}", self.episodes(data), id="episodes"),
        ]
        if data.horizon is not None:
            panes.append(TabPane("Horizon", self.horizon(data.horizon), id="horizon"))
        tabs = TabbedContent(id="task-tabs")
        for pane in panes:
            tabs.compose_add_child(pane)
        yield tabs

    def facts(self, data: TaskDetail) -> Iterable[Facts]:
        row = data.row
        dot = f" {self.gauntlet.look.glyphs.dot} "
        pr = f"#{row.pr_number} {row.pr_title}" if row.pr_number is not None else row.pr_title
        yield Facts(
            [
                Fact("Repo", row.repo),
                Fact("PR" if row.category == "swe" else "Range", pr),
                Fact("URL", row.pr_url or fmt.MISSING),
                Fact("Merged", fmt.date_time(row.merged_at), copy=row.merged_at or ""),
                Fact("Kind", dot.join([row.category, row.runner, row.language])),
                Fact("Statement", STATEMENT_SOURCES.get(row.statement_source, row.statement_source)),
            ],
            id="facts-pr",
        )
        yield Facts(
            [
                Fact("Dataset", row.dataset_id),
                Fact("Image", data.image),
                Fact("Fingerprint", data.env_fingerprint),
                Fact("Base", data.base_commit),
                Fact("Solution", data.solution_commit),
                Fact("Workdir", data.workdir),
            ],
            id="facts-env",
        )

    def statement(self, data: TaskDetail) -> VerticalScroll:
        where = STATEMENT_SOURCES.get(data.row.statement_source, data.row.statement_source)
        intro = _intro(f"What the agent reads, taken from {where}. It's shown as plain text, as written.")
        body = Static(fmt.safe_text(data.problem_statement), id="statement-text")
        return VerticalScroll(intro, body)

    def tests(self, data: TaskDetail) -> Iterable[Widget]:
        row = data.row
        counts: dict[TestClass, int] = {"f2p": row.f2p, "n2p": row.n2p, "s2p": row.s2p, "p2p": row.p2p}
        summary: list[Widget] = [_intro(TESTS_INTRO), TestClasses(counts)]
        if data.test_scope:
            summary.append(Heading("Scope", f"only part of the suite runs: {', '.join(data.test_scope)}"))
        if data.validation is not None:
            runs = data.validation
            notes = [f"scope {runs.scope}"] if runs.scope else []
            if runs.seconds_total is not None:
                notes.append(f"{fmt.duration(runs.seconds_total)} in all")
            summary += [Heading("Validation", ", ".join(notes)), ValidationTable(runs)]
        else:
            summary.append(Heading("Validation", "no validation record was shipped with this task"))
        summary += [
            IdList("Fail to pass", data.f2p),
            IdList("New to pass", data.n2p),
            IdList("Skipped to pass", data.s2p),
            IdList("Flaky", data.flaky, note="left out of grading"),
            IdList("Test files", data.test_files, note="hidden from the agent"),
        ]
        p2p = Deferred(
            partial(self.source.task_tests, self.instance_id, "p2p"), self.pass_to_pass, what="the tests"
        )
        dot = self.gauntlet.look.glyphs.dot
        yield Horizontal(
            VerticalScroll(*summary, id="tests-summary"),
            _pane(f"Pass to pass {dot} {fmt.count(row.p2p)}", p2p, id="p2p-pane"),
            id="tests-split",
        )

    def pass_to_pass(self, tests: tuple[str, ...]) -> Iterable[Widget]:
        yield PassToPass(self.instance_id, tests)

    def leaks(self, data: TaskDetail) -> VerticalScroll:
        items = [CheckItem(check.label, check.ok, check.detail) for check in data.leakchecks]
        return VerticalScroll(_intro(LEAK_INTRO), Checklist(items, failed=LEAK_FAILED, id="leak-checks"))

    def patches(self, data: TaskDetail) -> Iterable[Widget]:
        look = self.gauntlet.look
        yield _intro(PATCH_INTRO)
        for title, patch, cut, pane_id in (
            ("Merged fix", data.gold_patch, data.gold_patch_truncated, "gold-pane"),
            ("Hidden tests", data.test_patch, data.test_patch_truncated, "test-pane"),
        ):
            view = DiffView(patch, empty="No patch shipped.")
            title = f"{title} {look.glyphs.dot} {fmt.plural(len(view.diff.files), 'file')}"
            pane = _pane(title, view, id=pane_id, classes="patch")
            if cut:
                pane.border_subtitle = f"{look.symbol(WARNING)} {PATCH_CUT}"
            yield pane

    def episodes(self, data: TaskDetail) -> DataGrid[EpisodeRow]:
        grid: DataGrid[EpisodeRow] = DataGrid(
            EPISODE_COLUMNS, key=episode_key, empty=NO_EPISODES, what="run/episode id", id="episodes-grid"
        )
        grid.set_rows(data.episodes)
        return grid

    def horizon(self, horizon: HorizonDetail) -> VerticalScroll:
        dot = self.gauntlet.look.glyphs.dot
        facts = Definitions(
            [
                Definition("Range", f"{horizon.from_ref} to {horizon.to_ref}"),
                Definition(
                    "Gold size", f"{fmt.plural(horizon.gold_lines, 'line')} added or removed in the source"
                ),
            ]
        )
        prs = [Definition(f"#{pr.number}", pr.title) for pr in horizon.prs]
        milestones = [
            Definition(m.id, f"{m.title} {dot} {fmt.plural(m.tests, 'test')}") for m in horizon.milestones
        ]
        return VerticalScroll(
            _intro(HORIZON_INTRO),
            facts,
            *_titled("PRs", prs),
            IdList("Direct commits", horizon.direct_commits, note="landed without a PR"),
            *_titled("Milestones", milestones),
            IdList("Dropped regressions", horizon.dropped_regressions, note="left out of grading"),
            id="horizon-body",
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "filter":
            tabs = self.query(TabbedContent)
            return bool(tabs) and tabs.first().active == TESTS_TAB and bool(self.query(FilterBar))
        return super().check_action(action, parameters)

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        self.refresh_bindings()
        for widget in event.pane.query("*"):
            if widget.focusable and not isinstance(widget, Input):
                widget.focus()
                return

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        if isinstance(event.row, EpisodeRow):
            self.gauntlet.open_episode(event.row.run_id, event.row.episode_id)

    def copy_target(self) -> tuple[str, str] | None:
        return self.instance_id, "instance id"
