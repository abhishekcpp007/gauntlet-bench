"""Workbench (`5`): make tasks, check them and score them, without leaving the viewer.

The machine line on top says what this machine can do right now: Docker, free disk, whether an
Anthropic key is set (never its value) and the workspace. The Actions tab lists the actions in
their groups with what the focused one does and needs, and its form beside it. The Jobs tab lists
every job, newest first; `enter` opens one. A form's review opens the confirm step, and `enter`
there starts the job and lands on its screen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import ClassVar

from rich.console import RenderableType
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import ContentSwitcher, OptionList, TabbedContent, TabPane
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..jobtypes import ActionInfo, JobEvent, JobRecord, JobSpec, Machine
from ..theme import ERROR, KEY_SET, NO_FORM, NO_KEY, PASSED, WARNING, Look
from ..widgets.form import FormView
from ..widgets.grid import Column, DataGrid
from ..widgets.jobstatus import ACTIVE, GIGABYTE, disk_size, elapsed, job_mark
from ..widgets.states import Empty, describe_error
from ..widgets.themed import Themed
from ..workbench.base import GROUPS, NEED_LABELS, ActionForm, blocked_reason, check_needs
from ..workspace import Workspace, WorkspaceError
from .base import GauntletScreen
from .confirm import ConfirmJob

ACTIONS_TAB = "actions"
NARROW = 110
JOBS_TAB = "jobs"
MACHINE_GROUP = "machine"
LOW_DISK_GB = 20
LOW_DISK_BYTES = LOW_DISK_GB * GIGABYTE
MIN_PATH_WIDTH = 16
CHECKING = "Checking the machine first."
NO_JOBS = Empty("No jobs yet.", "Pick an action, fill in its form and press ctrl+r to review it.")
NO_FORM_YET = "This action doesn't have a form in the Workbench yet."
NO_FORM_HINT = "Run it from the command line for now: gauntlet --help lists every command."


def shown_path(path: str, here: Path | None = None) -> str:
    """`path` as a folder under the current one, when it is one, so the line says `gauntlet-work`
    rather than the whole path from the root. Any other path is shown whole."""
    try:
        return str(Path(path).relative_to(here or Path.cwd()))
    except ValueError:
        return path


def machine_line(
    machine: Machine | None, look: Look, error: str | None = None, *, width: int | None = None
) -> Text:
    """`✓ Docker running · 42.1 GB free · ✗ no Anthropic key · workspace ./gauntlet-work`. Given a
    `width`, a long workspace path is cut in the middle so both ends show, and goes on a line of
    its own when there's too little room beside the rest."""
    dot = look.muted(f"  {look.glyphs.dot}  ")
    if error is not None:
        return Text.assemble(look.mark(ERROR, word=False), f" Couldn't check the machine: {error}")
    if machine is None:
        return look.muted(f"Checking the machine{look.glyphs.ellipsis}")
    text = Text(end="", no_wrap=True, overflow=look.overflow)
    if machine.docker_running:
        text.append_text(look.mark(PASSED, word=False))
        text.append(" Docker running")
    else:
        text.append_text(look.mark(ERROR, word=False))
        text.append(" Docker isn't running", style=look.style("bad"))
        text.append_text(look.muted(f" ({fmt.one_line(machine.docker_detail)})"))
    text.append_text(dot)
    low = machine.free_disk_bytes < LOW_DISK_BYTES
    if low:
        text.append_text(look.mark(WARNING, word=False))
        text.append(" ")
    text.append(f"{disk_size(machine.free_disk_bytes)} free", style=look.style("warn") if low else "")
    text.append_text(dot)
    key = KEY_SET if machine.anthropic_key_set else NO_KEY
    text.append_text(look.mark(key, word=False))
    text.append(f" {key.word}", style=look.style("muted") if not machine.anthropic_key_set else "")
    path = fmt.visible(fmt.one_line(shown_path(machine.workspace)))
    label = look.muted("workspace ")
    if width is None:
        text.append_text(dot)
    else:
        text.truncate(width, overflow=look.overflow)
        room = width - text.cell_len - dot.cell_len - label.cell_len
        if room < min(len(path), MIN_PATH_WIDTH):
            text.append("\n")
            room = width - label.cell_len
        else:
            text.append_text(dot)
        path = fmt.middle(path, max(room, MIN_PATH_WIDTH), look.glyphs.ellipsis)
    text.append_text(label)
    text.append_text(fmt.safe_text(path, single_line=True))
    return text


class MachineLine(Themed):
    DEFAULT_CSS = """
    MachineLine {
        height: auto;
        padding: 0 1;
        margin: 1 0 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(id="machine")
        self.machine: Machine | None = None
        self.error: str | None = None

    def show(self, machine: Machine | None, error: str | None = None) -> None:
        self.machine = machine
        self.error = error
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        return machine_line(self.machine, self.look, self.error, width=self.content_size.width)


class ActionList(OptionList):
    """The actions in their groups. Moving through it shows each one's form."""

    HELP_GROUP = "Actions"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("enter", "select", "Fill in"),
    ]


class ActionAbout(Themed):
    """What the focused action does and needs, and why it can't start if it can't."""

    DEFAULT_CSS = """
    ActionAbout {
        height: auto;
        padding: 1 1 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.info: ActionInfo | None = None
        self.blocked: str | None = None

    def show(self, info: ActionInfo | None, blocked: str | None) -> None:
        self.info = info
        self.blocked = blocked
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        info = self.info
        if info is None:
            return Text("")
        text = Text(info.description, end="")
        text.append("\n\n")
        text.append_text(look.muted("Needs  "))
        if not info.needs:
            text.append("nothing but this machine")
        for index, need in enumerate(info.needs):
            if index:
                text.append_text(look.muted(f" {look.glyphs.dot} "))
            text.append(NEED_LABELS[need])
        if self.blocked:
            text.append("\n\n")
            text.append_text(look.mark(WARNING, word=False))
            text.append(" Can't start  ", style=look.style("warn", bold=True))
            text.append_text(fmt.safe_text(self.blocked))
        return text


class NoForm(Themed):
    """In place of a form, for an action the Workbench lists but can't run yet."""

    DEFAULT_CSS = """
    NoForm {
        height: 1fr;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, info: ActionInfo) -> None:
        super().__init__(id=info.id)
        self.info = info

    def render(self) -> RenderableType:
        look = self.look
        text = Text.assemble(look.mark(NO_FORM), "\n\n")
        text.append(NO_FORM_YET)
        text.append("\n")
        text.append_text(look.muted(NO_FORM_HINT))
        return text


def _state(record: JobRecord, look: Look) -> Text:
    return job_mark(look, record.state)


def _started(record: JobRecord, look: Look) -> Text:
    stamp = record.started_at if record.started_at is not None else record.created_at
    return Text(fmt.date_time(stamp), end="")


def _elapsed(record: JobRecord, look: Look) -> Text:
    took = elapsed(record)
    return look.muted(fmt.MISSING) if took is None else Text(fmt.duration(took), end="")


JOB_COLUMNS: tuple[Column[JobRecord], ...] = (
    Column("state", "State", lambda r: r.state, render=_state),
    Column("title", "Job", lambda r: r.spec.title, kind="text", shrink=True),
    Column("action", "Action", lambda r: r.spec.action, priority=4),
    Column("started", "Started", lambda r: r.started_at or r.created_at, render=_started, priority=2),
    Column("elapsed", "Elapsed", lambda r: elapsed(r), render=_elapsed, priority=3),
    Column("id", "Id", lambda r: r.id, kind="id", priority=5),
)


def newest_first(records: Sequence[JobRecord]) -> list[JobRecord]:
    return sorted(records, key=lambda r: r.created_at, reverse=True)


class WorkbenchScreen(GauntletScreen):
    """See the module docstring."""

    HELP_GROUP = "Workbench"
    HELP_EVERY_PANE = True
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("r", "recheck", "Recheck machine", show=False),
    ]

    CSS_PATH = "workbench.tcss"
    crumb = "Workbench"

    def __init__(self, actions: Sequence[ActionInfo], forms: Mapping[str, type[ActionForm]]) -> None:
        super().__init__()
        self.actions = tuple(actions)
        self.form_classes = dict(forms)
        self.machine: Machine | None = None
        self.workspace: Workspace | None = None
        self.forms: dict[str, FormView] = {}
        self.current: str | None = next(
            (info.id for info in self.actions if info.id in self.form_classes),
            self.actions[0].id if self.actions else None,
        )
        self._ticker: Timer | None = None

    def compose_body(self) -> ComposeResult:
        yield MachineLine()
        with TabbedContent(id="wb-tabs", initial=ACTIONS_TAB):
            with TabPane("Actions", id=ACTIONS_TAB), Horizontal(id="wb-main"):
                with Vertical(id="actions-pane", classes="pane") as left:
                    left.border_title = "Actions"
                    yield ActionList(*self.action_options(), id="action-list")
                    yield ActionAbout()
                with Vertical(id="form-pane", classes="pane") as right:
                    right.border_title = self.actions[0].title if self.actions else "Form"
                    right.border_subtitle = "ctrl+r reviews"
                    with ContentSwitcher(id="forms", initial=self.current):
                        for info in self.actions:
                            form = self.form_classes.get(info.id)
                            if form is None:
                                yield NoForm(info)
                                continue
                            view = FormView(form(), info=info, source=lambda: self.source, id=info.id)
                            self.forms[info.id] = view
                            yield view
            with TabPane("Jobs", id=JOBS_TAB):
                grid: DataGrid[JobRecord] = DataGrid(
                    JOB_COLUMNS, key=lambda r: r.id, empty=NO_JOBS, what="job id", id="job-grid"
                )
                pane = Vertical(grid, id="jobs-pane", classes="pane")
                pane.border_title = "Jobs"
                pane.border_subtitle = "newest first · enter opens one"
                yield pane

    def action_options(self) -> list[Option | None]:
        options: list[Option | None] = []
        for group, label in GROUPS:
            members = [info for info in self.actions if info.group == group]
            if not members:
                continue
            if options:
                options.append(None)
            options.append(Option(Text(label, style="bold"), disabled=True, id=f"group-{group}"))
            for info in members:
                options.append(Option(self.action_prompt(info), id=info.id))
        return options

    def action_prompt(self, info: ActionInfo) -> Text:
        look = self.gauntlet.look
        if info.id not in self.form_classes:
            return Text.assemble(look.muted(f"  {info.title}  "), look.mark(NO_FORM, word=False))
        text = Text(f"  {info.title}", end="")
        if self.machine is not None and blocked_reason(info.needs, self.machine):
            missing = [c.label for c in check_needs(info.needs, self.machine) if c.met is False]
            text.append_text(look.muted(f"  needs {' and '.join(missing)}"))
        return text

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.width < NARROW, "-narrow")

    def on_mount(self) -> None:
        super().on_mount()
        self.gauntlet.job_events.subscribe(self, self.on_job_events, immediate=True)
        self._ticker = self.set_interval(1, self.show_jobs, pause=True)
        self.query_one(ActionList).focus()
        self.highlight_first()
        self.show_jobs()
        self.recheck()

    def highlight_first(self) -> None:
        """Start on the first action that has a form, or the first action when none has one."""
        options = self.query_one(ActionList)
        usable = [info.id for info in self.actions if info.id in self.form_classes]
        first = usable[0] if usable else (self.actions[0].id if self.actions else None)
        if first is not None:
            options.highlighted = options.get_option_index(first)

    def info_for(self, action_id: str | None) -> ActionInfo | None:
        return next((info for info in self.actions if info.id == action_id), None)

    def blocked(self, info: ActionInfo) -> str | None:
        if self.machine is None:
            return CHECKING if info.needs else None
        return blocked_reason(info.needs, self.machine)

    def show_action(self, action_id: str) -> None:
        info = self.info_for(action_id)
        if info is None:
            return
        self.current = action_id
        self.query_one("#forms", ContentSwitcher).current = action_id
        pane = self.query_one("#form-pane")
        pane.border_title = info.title
        pane.border_subtitle = "ctrl+r reviews" if action_id in self.forms else ""
        blocked = self.blocked(info) if action_id in self.forms else None
        self.query_one(ActionAbout).show(info, blocked)
        self.refresh_bindings()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if isinstance(event.option_list, ActionList) and event.option.id:
            self.show_action(event.option.id)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if isinstance(event.option_list, ActionList) and event.option.id:
            self.show_action(event.option.id)
            if event.option.id in self.forms:
                self.forms[event.option.id].focus_first()

    @work(thread=True, exclusive=True, group=MACHINE_GROUP, exit_on_error=False)
    def recheck(self) -> Machine:
        jobs = self.gauntlet.jobs
        if jobs is None:
            raise LookupError("the Workbench has no job runner")
        return jobs.machine()

    def action_recheck(self) -> None:
        self.recheck()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != MACHINE_GROUP:
            return
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, Machine):
            self.set_machine(event.worker.result)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.query_one(MachineLine).show(None, describe_error(event.worker.error))

    def set_machine(self, machine: Machine) -> None:
        self.machine = machine
        self.query_one(MachineLine).show(machine)
        try:
            self.workspace = Workspace(machine.workspace)
        except WorkspaceError as error:
            self.query_one(MachineLine).show(machine, str(error))
            self.workspace = None
        for info in self.actions:
            view = self.forms.get(info.id)
            if view is not None:
                view.workspace = self.workspace
                view.set_blocked(self.blocked(info))
        options = self.query_one(ActionList)
        for info in self.actions:
            options.replace_option_prompt(info.id, self.action_prompt(info))
        if self.current is not None:
            self.show_action(self.current)

    def on_form_view_reviewed(self, event: FormView.Reviewed) -> None:
        event.stop()
        spec = event.spec
        reason = blocked_reason(spec.needs, self.machine) if self.machine is not None else CHECKING
        if reason:
            event.view.set_blocked(reason)
            return
        waits = spec.exclusive and any(
            r.spec.exclusive and r.state in ACTIVE for r in self.gauntlet.job_records.values()
        )

        def answered(start: bool | None) -> None:
            if start:
                self.submit(spec)

        self.app.push_screen(ConfirmJob(spec, self.machine, waits=waits), answered)

    @work(thread=True, group="submit", exit_on_error=False)
    def submit(self, spec: JobSpec) -> None:
        jobs = self.gauntlet.jobs
        if jobs is None:
            return
        try:
            record = jobs.submit(spec)
        except Exception as error:  # a refused job gets one line, and the form keeps its values
            self.app.call_from_thread(
                self.notify,
                f"Couldn't start the job: {describe_error(error)}",
                severity="error",
                markup=False,
            )
            return
        self.app.call_from_thread(self.started, record)

    def started(self, record: JobRecord) -> None:
        self.gauntlet.remember_job(record)
        self.show_jobs()
        self.gauntlet.open_job(record.id)

    def on_job_events(self, events: tuple[JobEvent, ...]) -> None:
        self.show_jobs()
        if any(e.kind == "state" and e.record.state not in ACTIVE for e in events):
            self.recheck()

    def show_jobs(self) -> None:
        records = newest_first(list(self.gauntlet.job_records.values()))
        grid: DataGrid[JobRecord] = self.query_one("#job-grid", DataGrid)
        grid.set_rows(records)
        tabs = self.query_one("#wb-tabs", TabbedContent)
        tabs.get_tab(JOBS_TAB).label = f"Jobs {fmt.count(len(records))}" if records else "Jobs"
        if self._ticker is not None:
            if any(r.state == "running" for r in records):
                self._ticker.resume()
            else:
                self._ticker.pause()

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        if event.grid.id == "job-grid":
            self.gauntlet.open_job(event.key)

    def show_tab(self, tab: str) -> None:
        self.query_one("#wb-tabs", TabbedContent).active = tab

    def open_action(self, action_id: str, prefill: Mapping[str, str]) -> None:
        """Show `action_id` on the Actions tab with `prefill` in its form (`FormView.prefill`).
        An action with no form shows its "not available" note, and an unknown id changes nothing."""
        if self.info_for(action_id) is None:
            return
        self.show_tab(ACTIONS_TAB)
        options = self.query_one(ActionList)
        options.highlighted = options.get_option_index(action_id)
        self.show_action(action_id)
        view = self.forms.get(action_id)
        if view is None:
            self.call_after_refresh(options.focus)
        else:
            self.call_after_refresh(view.prefill, dict(prefill))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        super().on_tabbed_content_tab_activated()
        if event.pane.id == JOBS_TAB:
            self.call_after_refresh(self.query_one("#job-grid", DataGrid).focus_table)
        else:
            self.call_after_refresh(self.query_one(ActionList).focus)

    def copy_target(self) -> tuple[str, str] | None:
        if self.machine is not None:
            return self.machine.workspace, "workspace path"
        return None
