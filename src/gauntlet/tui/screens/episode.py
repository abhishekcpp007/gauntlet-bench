"""Episode: why this score.

Facts at the top (the task, the policy, the reward large on the diverging scale, the verdict,
whether it resolved, steps and time), then a tab for each part of the answer: how the reward was
made, the evidence Cheat Catcher and the grader found, the tests, the rubric, the patch, the
agent's steps and where the episode ran. A summary row says what wasn't shipped in each tab.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import ClassVar

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Collapsible, DataTable, Digits, Input, Static, TabbedContent, TabPane
from textual.worker import WorkerState

from .. import format as fmt
from ..models import (
    ClassCounts,
    EpisodeDetail,
    Facet,
    Finding,
    GradeDetail,
    TestClass,
    TestStatus,
    Trajectory,
)
from ..theme import (
    ERROR,
    FAILED,
    PASSED,
    SEVERITIES,
    SUMMARY_ONLY,
    TAMPERED,
    VERDICTS,
    WARNING,
    Look,
    Mark,
    look_for,
    reward_color,
)
from ..widgets.checklist import CheckItem, Checklist
from ..widgets.deferred import Deferred
from ..widgets.diff import DiffView
from ..widgets.facts import Fact, Facts
from ..widgets.filterbar import FacetGroup, FilterBar
from ..widgets.grid import Column, DataGrid
from ..widgets.rewardbar import PatchState, RewardBar
from ..widgets.states import Empty, EmptyState
from ..widgets.themed import Themed
from ..widgets.timeline import Timeline
from .base import DataScreen

TEST_CLASSES: tuple[TestClass, ...] = ("f2p", "n2p", "s2p", "p2p")
CLASS_MEANING: dict[TestClass, str] = {
    "f2p": "fail to pass: tests the fix makes pass",
    "n2p": "new to pass: tests that didn't run before the fix",
    "s2p": "skip to pass: tests the fix un-skips",
    "p2p": "pass to pass: tests that passed before and must keep passing",
}
MAX_FAILED_SHOWN = 5
FILTER_DELAY = 0.15
COLUMN_GAP = 2
MARK_GAP = 1
FULL_RATE = 1.0

SKIPPED = replace(SUMMARY_ONLY, word="skipped")
NO_RESULT = replace(SUMMARY_ONLY, word="no result")
IGNORED = replace(SUMMARY_ONLY, word="ignored")
NOT_RECORDED = replace(SUMMARY_ONLY, word="not recorded")
TEST_MARKS: dict[str, Mark] = {"PASSED": PASSED, "FAILED": FAILED, "SKIPPED": SKIPPED, "NONE": NO_RESULT}

NOTHING_FOUND = "Nothing found. Cheat Catcher gave a clean verdict and the grader saw no tampering."
NOT_SHIPPED = "summary row: the full record wasn't shipped"
NO_TRAJECTORY = Empty(
    "No trajectory was recorded for this episode.",
    "Shipped results don't include them. A run folder from gauntlet run has one per episode.",
)
NO_TESTS = Empty("No test ids match.", "Change the filter, or press esc to clear it.")


def patch_state(data: EpisodeDetail) -> PatchState | None:
    """What happened to the patch, in the order `compute_reward` checks it."""
    if data.patch is None:
        return None
    if not data.patch.strip():
        return "empty"
    if data.grade is not None and not data.grade.patch_applied:
        return "failed"
    return "applied"


class RewardDigits(Digits):
    """The reward in large digits, coloured on the diverging scale."""

    def __init__(self, reward: float) -> None:
        super().__init__(fmt.reward(reward).strip(), id="reward-digits")
        self.reward = reward

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._paint())
        self._paint()

    def _paint(self) -> None:
        self.styles.color = reward_color(self.reward, look_for(self).palette)


class Score(Themed):
    """The reward as bold text, for --ascii where the large digits can't draw."""

    def __init__(self, reward: float) -> None:
        super().__init__(id="reward-text")
        self.reward = reward

    def render(self) -> RenderableType:
        return self.look.reward(self.reward, bold=True)


Group = tuple[Mark, str, str, tuple[str, ...]]


def evidence_groups(data: EpisodeDetail) -> list[Group]:
    """What the grader saw besides Cheat Catcher: mark, title, what it means, items. Empty groups
    are left out."""
    grade = data.grade
    out: list[Group] = []
    if grade is not None and grade.tampered:
        meaning = (
            "The grader caught this at run time: a canary that came back wrong, or a watched file "
            "whose hash changed."
        )
        out.append((TAMPERED, "Grader tamper checks", meaning, grade.tampered))
    elif grade is None and data.row.tampered:
        out.append(
            (TAMPERED, "Grader tamper checks", "The grader flagged tampering. Its messages weren't kept.", ())
        )
    if grade is not None and grade.ignored_files:
        meaning = (
            "Edits the grader threw away before grading. Changes to test and config files never reach "
            "the test run."
        )
        out.append((IGNORED, "Ignored files", meaning, grade.ignored_files))
    if grade is not None and grade.compile_errors:
        out.append(
            (WARNING, "Compile errors", "Files in the patch that didn't compile.", grade.compile_errors)
        )
    if grade is not None and grade.error:
        out.append((ERROR, "Grader error", "The grader stopped with this error.", (grade.error,)))
    return out


class EvidenceGroups(Themed):
    """The groups from `evidence_groups`, each with its one plain line."""

    DEFAULT_CSS = """
    EvidenceGroups {
        height: auto;
    }
    """

    def __init__(self, groups: list[Group]) -> None:
        super().__init__(id="evidence-groups")
        self.groups = groups

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, MARK_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        for index, (mark, title, meaning, items) in enumerate(self.groups):
            if index:
                grid.add_row(Text(""), Text(""))
            heading = Text(title, style="bold", end="")
            if items:
                heading.append(f"  {fmt.count(len(items))}", style=look.style("muted"))
            grid.add_row(look.mark(mark, word=False), heading)
            grid.add_row(Text(""), look.muted(meaning))
            for item in items:
                grid.add_row(Text(""), fmt.safe_text(item, style=look.style(mark.tone)))
        return grid


class TestSummary(Themed):
    """Per class: how many passed out of how many, the ids that didn't pass first; then the
    milestones on a long-horizon task."""

    __test__ = False

    DEFAULT_CSS = """
    TestSummary {
        height: auto;
    }
    """

    def __init__(self, grade: GradeDetail) -> None:
        super().__init__(id="test-summary")
        self.grade = grade

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, COLUMN_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column(ratio=1)
        for cls in TEST_CLASSES:
            counts: ClassCounts = getattr(self.grade, cls)
            name = Text(cls.upper(), style="bold", end="")
            if counts.total == 0:
                grid.add_row(name, look.muted("none"), look.muted(CLASS_MEANING[cls]))
                continue
            mark = look.mark(PASSED if counts.passed == counts.total else FAILED, word=False)
            grid.add_row(
                name,
                mark + Text(f" {fmt.ratio(counts.passed, counts.total)}"),
                look.muted(CLASS_MEANING[cls]),
            )
            for test in counts.failed[:MAX_FAILED_SHOWN]:
                grid.add_row(Text(""), look.muted("didn't pass"), fmt.safe_text(test, single_line=True))
            if len(counts.failed) > MAX_FAILED_SHOWN:
                rest = fmt.count(len(counts.failed) - MAX_FAILED_SHOWN)
                grid.add_row(
                    Text(""), Text(""), look.muted(f"and {rest} more: filter the list below by status")
                )
        if self.grade.milestones:
            grid.add_row(Text(""), Text(""), Text(""))
            grid.add_row(
                Text("Milestones", style="bold"),
                Text(""),
                look.muted("one per PR in the release range, each the share of its tests that pass"),
            )
            for milestone, rate in self.grade.milestones:
                mark = look.mark(PASSED if rate >= FULL_RATE else FAILED, word=False)
                grid.add_row(
                    fmt.safe_text(milestone, single_line=True), mark + Text(f" {fmt.percent(rate)}"), Text("")
                )
        return grid


def finding_columns(findings: Iterable[Finding]) -> tuple[Column[tuple[int, Finding]], ...]:
    """The findings table's columns, with the message as wide as the longest one."""
    widest = max((len(f.message) for f in findings), default=0)
    return (
        Column("severity", "Severity", lambda r: SEVERITIES[r[1].severity], kind="mark"),
        Column("rule", "Rule", lambda r: r[1].rule, kind="id"),
        Column("message", "Message", lambda r: r[1].message, width=widest or None, shrink=True),
        Column("file", "File", lambda r: r[1].file, kind="id", priority=3),
        Column("step", "Step", lambda r: r[1].step, kind="number", priority=2),
    )


def test_columns(tests: Iterable[TestStatus]) -> tuple[Column[TestStatus], ...]:
    """The test list's columns, with the id column as wide as the longest id so it isn't cut early."""
    widest = max((len(t.id) for t in tests), default=0)
    return (
        Column("status", "Status", lambda t: TEST_MARKS[t.status], kind="mark"),
        Column("class", "Class", lambda t: t.test_class.upper() if t.test_class else None),
        Column("id", "Test", lambda t: t.id, kind="id", width=widest or None, shrink=True),
    )


def _facets(values: Iterable[str]) -> tuple[Facet, ...]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(Facet(k, n) for k, n in counts.items())


def rubric_items(data: EpisodeDetail, look: Look) -> list[CheckItem]:
    """Rubric items as checklist rows. A pitfall passes when the patch didn't fall into it."""
    out = []
    dot = look.glyphs.dot
    for item in data.rubric_items:
        pitfall = item.category == "pitfall"
        ok = not item.met if pitfall else item.met
        state = ("fell into it" if item.met else "avoided") if pitfall else ("met" if item.met else "not met")
        detail = f"{item.category} {dot} {state} {dot} score {item.score:.{fmt.REWARD_DIGITS}f}"
        if item.rationale:
            detail += f" {dot} {item.rationale}"
        out.append(CheckItem(item.id, ok, detail))
    return out


class EpisodeScreen(DataScreen[EpisodeDetail]):
    CSS_PATH = "episode.tcss"
    what = "the episode"

    BINDINGS: ClassVar[list[BindingType]] = [Binding("t", "open_task", "Open task")]

    def __init__(self, run_id: str, episode_id: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.episode_id = episode_id
        self.crumb = episode_id
        self.detail: EpisodeDetail | None = None
        self.tests: tuple[TestStatus, ...] = ()
        self._pending_step: int | None = None
        self._filter_timer: Timer | None = None

    def fetch(self) -> EpisodeDetail:
        return self.source.episode(self.run_id, self.episode_id)

    def build(self, data: EpisodeDetail) -> Iterable[Widget]:
        self.detail = data
        look = self.gauntlet.look
        yield self._head(data, look)
        if data.row.error:
            line = look.mark(ERROR, word=False)
            line.append(" The episode crashed: ", style=look.style("bad", bold=True))
            line.append_text(fmt.safe_text(data.row.error, single_line=True, style=look.style("bad")))
            line.append_text(look.muted("  No verdict was recorded, so the clean one above means nothing."))
            yield Static(line, id="episode-error")
        if data.row.detail == "summary":
            note = look.mark(SUMMARY_ONLY, word=False)
            note.append_text(
                look.muted(" Summary row: the full record wasn't shipped. The tabs show what was.")
            )
            yield Static(note, id="episode-summary", classes="episode-note")
        tabs = TabbedContent(id="episode-tabs")
        for pane in self._panes(data, look):
            tabs.compose_add_child(pane)
        yield tabs
        self.call_after_refresh(self.focus_tab)
        self.call_after_refresh(self.refresh_bindings)

    def _head(self, data: EpisodeDetail, look: Look) -> Widget:
        row = data.row
        score: Widget = Score(row.reward) if look.ascii else RewardDigits(row.reward)
        if row.error:
            verdict = look.mark(NOT_RECORDED) + look.muted(" (it crashed)")
        else:
            verdict = look.mark(VERDICTS[row.cheat_verdict])
        resolved = look.mark(PASSED if row.resolved else FAILED, word=False)
        resolved.append(" resolved" if row.resolved else " not resolved")
        ran = [
            fmt.plural(row.steps, "step") if row.steps is not None else fmt.MISSING,
            fmt.duration(row.seconds),
        ]
        if row.attempt is not None:
            ran.append(f"attempt {row.attempt}")
        ran_text = f" {look.glyphs.dot} ".join(r for r in ran if r != fmt.MISSING) or fmt.MISSING
        left = Facts(
            [
                Fact("Task", row.instance_id),
                Fact("Policy", Text(row.policy) + look.muted(f"  {row.policy_kind}"), copy=row.policy),
                Fact("Run", row.run_id),
            ],
            id="episode-facts",
        )
        right = Facts(
            [
                Fact("Verdict", verdict, copy=row.cheat_verdict),
                Fact("Resolved", resolved, copy=str(row.resolved).lower()),
                Fact("Ran", ran_text),
            ],
            id="episode-status",
        )
        block = Vertical(score, id="episode-score")
        head = Horizontal(block, left, right, id="episode-head", classes="pane")
        head.border_title = "Episode"
        head.border_subtitle = "t opens the task"
        return head

    def _panes(self, data: EpisodeDetail, look: Look) -> list[TabPane]:
        steps = data.trajectory_steps
        evidence = f"Evidence {len(data.findings)}" if data.findings else "Evidence"
        return [
            TabPane("Reward", self._reward_tab(data), id="reward"),
            TabPane(evidence, self._evidence_tab(data, look), id="evidence"),
            TabPane("Tests", self._tests_tab(data), id="tests"),
            TabPane("Rubric", self._rubric_tab(data, look), id="rubric"),
            TabPane("Patch", self._patch_tab(data), id="patch"),
            TabPane(
                f"Trajectory {steps}" if steps else "Trajectory", self._trajectory_tab(), id="trajectory"
            ),
            TabPane("Provenance", self._provenance_tab(data, look), id="provenance"),
        ]

    def _reward_tab(self, data: EpisodeDetail) -> Widget:
        row = data.row
        bar = RewardBar(
            data.reward_breakdown,
            row.reward,
            row.cheat_verdict,
            row.resolved,
            patch=patch_state(data),
            id="reward-bar",
        )
        return VerticalScroll(bar, id="reward-scroll")

    def _evidence_tab(self, data: EpisodeDetail, look: Look) -> Widget:
        if data.row.detail == "summary":
            text = Text(f"Cheat Catcher's findings weren't shipped ({NOT_SHIPPED}). Its verdict was ", end="")
            text.append_text(look.mark(VERDICTS[data.row.cheat_verdict]))
            text.append(".")
            if data.row.tampered:
                text.append("\nThe grader flagged tampering on this episode.", style=look.style("bad"))
            return VerticalScroll(Static(text, id="evidence-empty"))
        children: list[Widget] = []
        if data.findings:
            intro = (
                "Cheat Catcher read the patch and the agent's steps. A high finding makes the verdict "
                "cheating. Press enter on a finding with a step to see that step."
            )
            children.append(Static(intro, markup=False, classes="intro"))
            grid: DataGrid[tuple[int, Finding]] = DataGrid(
                finding_columns(data.findings), key=lambda r: str(r[0]), what="rule id", id="findings"
            )
            grid.set_rows(list(enumerate(data.findings)))
            pane = Vertical(grid, id="findings-pane", classes="pane")
            pane.border_title = f"Cheat Catcher findings {look.glyphs.dot} {len(data.findings)}"
            children.append(pane)
            children.append(Static(self._evidence_line(data.findings[0]), id="finding-evidence"))
        groups = evidence_groups(data)
        if groups:
            children.append(EvidenceGroups(groups))
        if not children:
            clean = data.row.cheat_verdict == "clean"
            message = NOTHING_FOUND if clean else "No findings were recorded, though the verdict isn't clean."
            children.append(Static(message, markup=False, id="evidence-empty"))
        return VerticalScroll(*children, id="evidence-scroll")

    def _tests_tab(self, data: EpisodeDetail) -> Widget:
        if data.row.detail == "summary":
            word = "resolved" if data.row.resolved else "didn't resolve"
            message = f"Test results weren't shipped ({NOT_SHIPPED}). The episode {word}."
            return VerticalScroll(Static(message, markup=False, id="tests-empty"))
        if data.grade is None:
            message = "The grader didn't run for this episode, so there are no test results."
            return VerticalScroll(Static(message, markup=False, id="tests-empty"))
        summary = VerticalScroll(TestSummary(data.grade), id="test-summary-scroll")
        listing = Deferred(self._fetch_tests, self._build_tests, what="the test list", id="tests-list")
        pane = Vertical(listing, id="tests-pane", classes="pane")
        pane.border_title = "All tests"
        return Vertical(summary, pane, id="tests-body")

    def _rubric_tab(self, data: EpisodeDetail, look: Look) -> Widget:
        score = Text("Rubric score  ", style="bold", end="")
        score.append(
            fmt.MISSING if data.rubric_score is None else f"{data.rubric_score:.{fmt.REWARD_DIGITS}f}"
        )
        if data.row.detail == "summary":
            note = Static(f"The items weren't shipped ({NOT_SHIPPED}).", markup=False, classes="intro")
            return VerticalScroll(Static(score, id="rubric-score"), note)
        if data.rubric_score is None and not data.rubric_items:
            return VerticalScroll(
                Static("No rubric was scored for this episode.", markup=False, id="rubric-score")
            )
        intro = (
            "Each item is a check on the patch. A pitfall counts against the score when the patch "
            "falls into it."
        )
        children: list[Widget] = [
            Static(score, id="rubric-score"),
            Static(intro, markup=False, classes="intro"),
            Checklist(rubric_items(data, look), id="rubric-items"),
        ]
        if data.rubric_skipped:
            skipped = look.muted("Skipped, so they weren't scored and don't count either way: ")
            skipped.append_text(fmt.safe_text(", ".join(data.rubric_skipped)))
            children.append(Static(skipped, id="rubric-skipped"))
        return VerticalScroll(*children)

    def _patch_tab(self, data: EpisodeDetail) -> Widget:
        return Deferred(lambda: data, self._build_patch, what="the patch", id="patch-view")

    def _trajectory_tab(self) -> Widget:
        return Deferred(
            self._fetch_trajectory, self._build_trajectory, what="the trajectory", id="trajectory-view"
        )

    def _provenance_tab(self, data: EpisodeDetail, look: Look) -> Widget:
        p = data.provenance
        if p is None:
            why = f"({NOT_SHIPPED})" if data.row.detail == "summary" else "for this episode"
            return VerticalScroll(
                Static(f"No provenance was recorded {why}.", markup=False, id="provenance-empty")
            )
        facts = [
            Fact("Harness", p.harness_version),
            Fact("Image", p.image),
            Fact("Fingerprint", p.env_fingerprint),
            Fact("Seed", p.grading_seed or fmt.MISSING),
            Fact("Ran at", fmt.date_time(p.ran_at), copy=p.ran_at),
        ]
        facts.extend(Fact(f"param {k}", v) for k, v in p.policy_params)
        facts.extend(Fact(f"usage {k}", v) for k, v in data.usage)
        if data.truncated is not None:
            facts.append(Fact("Truncated", "yes: it ran out of steps" if data.truncated else "no"))
        children: list[Widget] = [Facts(facts, id="provenance-facts")]
        if data.prompt:
            prompt = Static(fmt.safe_text(data.prompt), id="prompt-text")
            title = "The prompt the agent was given"
            if look.ascii:
                children.append(
                    Collapsible(prompt, title=title, collapsed_symbol=">", expanded_symbol="v", id="prompt")
                )
            else:
                children.append(Collapsible(prompt, title=title, id="prompt"))
        return VerticalScroll(*children)

    def _fetch_tests(self) -> tuple[TestStatus, ...]:
        return self.source.episode_tests(self.run_id, self.episode_id)

    def _build_tests(self, tests: tuple[TestStatus, ...]) -> Iterable[Widget]:
        rank = {c: i for i, c in enumerate(TEST_CLASSES)}
        self.tests = tuple(
            sorted(tests, key=lambda t: (t.status == "PASSED", rank.get(t.test_class, len(rank))))
        )
        groups = [
            FacetGroup("status", "Status", _facets(t.status for t in self.tests)),
            FacetGroup("class", "Class", _facets(t.test_class for t in self.tests if t.test_class)),
        ]
        bar = FilterBar(groups, placeholder="type to filter test ids", id="tests-filter")
        grid: DataGrid[TestStatus] = DataGrid(
            test_columns(self.tests),
            key=lambda t: t.id,
            empty=Empty("No tests were recorded for this episode."),
            what="test id",
            id="test-grid",
        )
        grid.set_rows(self.tests)
        yield bar
        yield grid
        self.call_after_refresh(self._count_tests)

    def _count_tests(self) -> None:
        for bar in self.query("#tests-filter").results(FilterBar):
            bar.set_groups(bar.groups)
            bar.set_count(len(self.tests), len(self.tests))
        self.refresh_bindings()

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        if event.bar.id != "tests-filter":
            return
        if self._filter_timer is not None:
            self._filter_timer.stop()
        query, facets = event.query, event.facets
        self._filter_timer = self.set_timer(FILTER_DELAY, lambda: self.filter_tests(query, facets))

    def filter_tests(self, query: str, facets: dict[str, str]) -> None:
        needle = query.strip().lower()
        status, cls = facets.get("status"), facets.get("class")
        rows = [
            t
            for t in self.tests
            if (status is None or t.status == status)
            and (cls is None or t.test_class == cls)
            and (not needle or needle in t.id.lower())
        ]
        self.query_one("#test-grid", DataGrid).set_rows(rows, empty=NO_TESTS)
        self.query_one("#tests-filter", FilterBar).set_count(len(rows), len(self.tests))

    def _build_patch(self, data: EpisodeDetail) -> Iterable[Widget]:
        if data.patch is None:
            why = f"({NOT_SHIPPED})" if data.row.detail == "summary" else "for this episode"
            yield EmptyState(Empty(f"No patch was recorded {why}."), id="patch-empty")
            return
        if not data.patch.strip():
            hint = "An empty patch counts as malformed, so the reward is the penalty."
            yield EmptyState(Empty("The agent changed nothing.", hint), id="patch-empty")
            return
        if data.patch_truncated:
            look = self.gauntlet.look
            note = look.mark(WARNING, word=False)
            note.append_text(
                look.muted(" This patch is very large, so only its first part was kept for the viewer.")
            )
            yield Static(note, id="patch-truncated", classes="episode-note")
        pane = Vertical(DiffView(data.patch, id="patch"), id="patch-pane", classes="pane")
        pane.border_title = "The agent's patch"
        yield pane

    def _fetch_trajectory(self) -> Trajectory | None:
        return self.source.trajectory(self.run_id, self.episode_id)

    def _build_trajectory(self, trajectory: Trajectory | None) -> Iterable[Widget]:
        step, self._pending_step = self._pending_step, None
        if trajectory is None:
            if step is not None:
                self.notify("No trajectory was recorded, so there's no step to show.", markup=False)
            yield EmptyState(NO_TRAJECTORY, id="trajectory-empty")
            return
        timeline = Timeline(trajectory, open_step=step, id="timeline")
        look = self.gauntlet.look
        pane = Vertical(timeline, id="trajectory-pane", classes="pane")
        title = f"Steps {look.glyphs.dot} {len(trajectory.steps)}"
        if timeline.flagged:
            title += f" {look.glyphs.dot} {timeline.flagged} flagged"
        pane.border_title = title
        yield pane

    @property
    def active_tab(self) -> str | None:
        found = self.query(TabbedContent)
        return found.first().active if found else None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("filter", "facets") and (self.active_tab != "tests" or not self.query("#tests-filter")):
            return False
        if action == "open_task":
            return self.detail is not None
        return super().check_action(action, parameters)

    def on_tabbed_content_tab_activated(self, _event: TabbedContent.TabActivated) -> None:
        self.set_focus(None)
        self.call_after_refresh(self.focus_tab)
        self.refresh_bindings()

    def focus_tab(self) -> None:
        """Focus the first thing you can move around in on the active tab. A tab still loading
        is left with nothing focused, so its content takes the focus when it arrives."""
        tabs = self.query_one(TabbedContent)
        if not tabs.active:
            return
        found = [w for w in tabs.get_pane(tabs.active).query("*") if w.focusable and not isinstance(w, Input)]
        inner = [w for w in found if not any(o is not w and w in o.ancestors for o in found)]
        if inner:
            inner[0].focus()
        self.refresh_bindings()

    def action_open_task(self) -> None:
        if self.detail is not None:
            self.gauntlet.open_task(self.detail.row.instance_id)

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        if event.grid.id != "findings":
            return
        _, finding = event.row
        if finding.step is None:
            self.notify("This finding came from the patch, not from one of the agent's steps.", markup=False)
            return
        self.jump_to_step(finding.step)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        grid = event.data_table.parent
        if not isinstance(grid, DataGrid) or grid.id != "findings" or grid.current is None:
            return
        self.query_one("#finding-evidence", Static).update(self._evidence_line(grid.current[1]))

    def _evidence_line(self, finding: Finding) -> Text:
        if not finding.evidence:
            return Text("")
        line = self.gauntlet.look.muted("evidence  ")
        line.append_text(fmt.safe_text(finding.evidence, single_line=True))
        return line

    def jump_to_step(self, step: int) -> None:
        """Show the Trajectory tab with sandbox step `step` open, loading the trajectory if it must."""
        tabs = self.query_one(TabbedContent)
        found = self.query("#timeline").results(Timeline)
        timeline = next(iter(found), None)
        view = self.query_one("#trajectory-view", Deferred)
        if timeline is None and view.state == WorkerState.SUCCESS:
            self.notify("No trajectory was recorded, so there's no step to show.", markup=False)
            return
        tabs.active = "trajectory"
        if timeline is None:
            self._pending_step = step
        elif not timeline.show_step(step):
            self.notify(f"Step {step} isn't in the trajectory.", markup=False)

    def copy_target(self) -> tuple[str, str] | None:
        return self.episode_id, "episode id"
