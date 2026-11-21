"""Job: one job, live. And `TextFileScreen`, which shows a report or any text a job wrote.

On top, the state, the title, the step in progress (`step 2 of 2: build`) and the time it's taken,
ticking while it runs. Then the command lines exactly as they'd be typed (`c` copies them), the
live log (`f` follows, `/` searches), and once it's done the result line and what it made (`o`
opens it). `x` cancels after asking. The screen loads the record and the log's tail from the
runner, so a job that finished before it opened, or in an earlier session, shows the same way.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Vertical, VerticalScroll
from textual.events import Resize
from textual.timer import Timer
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..jobtypes import FINISHED, JobEvent, JobRecord, Output, Stream
from ..widgets.joblog import LOG_WINDOW, JobLog, LogLines
from ..widgets.jobstatus import (
    ACTIVE,
    SPINNER_FPS,
    command_line,
    elapsed,
    job_mark,
    result_line,
    step_line,
)
from ..widgets.states import ErrorState, describe_error
from ..widgets.themed import Themed
from ..workbench.base import form_for
from .base import GauntletScreen
from .confirm import ConfirmPrompt

PROMPT = "$ "
LOAD_GROUP = "job-load"
SHORT_HEIGHT = 30
CANCEL_DETAIL = "The harness gets an interrupt first so it can close its sandboxes, then a kill if it hangs."
OUTPUT_KINDS = {
    "prs": "PRs",
    "tasks": "task set",
    "rejected": "rejected",
    "run": "run",
    "report": "report",
    "scan": "scan",
    "text": "text",
}


@dataclass(frozen=True, slots=True)
class JobData:
    record: JobRecord
    lines: tuple[str, ...]
    earlier: bool


class JobHeader(Themed):
    """`✓ succeeded  Calibrate live` with the elapsed time, then the step or the result, then where
    the full log is."""

    DEFAULT_CSS = """
    JobHeader {
        height: auto;
        padding: 1 1 0 1;
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.record: JobRecord | None = None
        self.frame = 0

    def show(self, record: JobRecord) -> None:
        self.record = record
        self.refresh(layout=True)

    def tick(self) -> None:
        self.frame += 1
        self.refresh()

    def render(self) -> RenderableType:
        look = self.look
        record = self.record
        if record is None:
            return look.muted(f"Loading the job{look.glyphs.ellipsis}")
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1, no_wrap=True, overflow=look.overflow)
        grid.add_column(justify="right", no_wrap=True)
        title = Text.assemble(job_mark(look, record.state, frame=self.frame), "  ")
        title.append_text(fmt.safe_text(record.spec.title, single_line=True, style="bold"))
        took = elapsed(record)
        grid.add_row(title, Text(fmt.duration(took) if took is not None else "not started", end=""))
        dot = f" {look.glyphs.dot} "
        detail = step_line(record)
        if record.state in FINISHED:
            detail = result_line(record)
        elif record.state == "queued":
            detail = "waiting for the Docker job ahead of it"
        grid.add_row(look.muted(detail), Text(""))
        where = look.muted(f"job {record.id}{dot}started {fmt.date_time(record.started_at)}{dot}log ")
        where.append_text(fmt.safe_text(record.log_path, single_line=True))
        grid.add_row(where, Text(""))
        return grid


class Commands(Themed):
    """Each step's command line with a `$` in front, exactly as it'd be typed."""

    DEFAULT_CSS = """
    Commands {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.record: JobRecord | None = None

    def show(self, record: JobRecord) -> None:
        self.record = record
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="", overflow="fold")
        if self.record is None:
            return text
        for index, step in enumerate(self.record.spec.steps):
            if index:
                text.append("\n")
            current = self.record.state == "running" and index == self.record.step_index
            prompt = look.accent(look.glyphs.step + " ") if current else look.muted(PROMPT)
            text.append_text(prompt)
            text.append_text(fmt.safe_text(command_line(step)))
        return text


class Outputs(OptionList):
    """What the job made. `enter` or `o` opens the highlighted one."""

    HELP_GROUP = "Outputs"


def output_line(output: Output) -> Text:
    text = Text(f"{OUTPUT_KINDS.get(output.kind, output.kind):<10}", style="bold", end="")
    text.append_text(fmt.safe_text(output.label, single_line=True))
    text.append("  ")
    text.append_text(fmt.safe_text(output.path, single_line=True, style="dim"))
    return text


def overlap(loaded: Sequence[str], fresh: Sequence[str]) -> int:
    """How many of `fresh` are already the last lines of `loaded`, so a line that arrived while the
    log was loading isn't shown twice."""
    for size in range(min(len(loaded), len(fresh)), 0, -1):
        if list(loaded[-size:]) == list(fresh[:size]):
            return size
    return 0


class JobScreen(GauntletScreen):
    """See the module docstring."""

    CSS_PATH = "job.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("x", "cancel_job", "Cancel"),
        Binding("o", "open_output", "Open"),
        Binding("f", "toggle_follow", "Follow"),
        Binding("slash", "filter", "Search"),
        Binding("c", "copy_commands", "Copy"),
    ]

    def __init__(self, job_id: str) -> None:
        super().__init__()
        self.job_id = job_id
        self.crumb = job_id
        self.record: JobRecord | None = None
        self.loaded = False
        self.buffered: list[JobEvent] = []
        self._ticker: Timer | None = None

    def compose_body(self) -> ComposeResult:
        with Vertical(id="body"):
            yield JobHeader()
            commands = VerticalScroll(Commands(), id="job-commands", classes="pane")
            commands.border_title = "Commands"
            commands.border_subtitle = "c copies"
            yield commands
            log = Vertical(JobLog(), id="job-log", classes="pane")
            log.border_title = "Log"
            yield log
            made = Vertical(Outputs(), id="job-outputs", classes="pane")
            made.border_title = "Made"
            made.border_subtitle = "o opens"
            made.display = False
            yield made

    def on_mount(self) -> None:
        super().on_mount()
        self.gauntlet.job_events.subscribe(self, self.on_job_events, immediate=True)
        self._ticker = self.set_interval(1 / SPINNER_FPS, self._tick, pause=True)
        self.query_one(LogLines).focus()
        self.load()

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.height < SHORT_HEIGHT, "-short")

    def load(self) -> None:
        self.run_worker(self.fetch, thread=True, group=LOAD_GROUP, exit_on_error=False)

    def fetch(self) -> JobData:
        jobs = self.gauntlet.jobs
        if jobs is None:
            raise LookupError("the Workbench isn't on")
        record = jobs.job(self.job_id)
        lines = jobs.log(self.job_id, tail=LOG_WINDOW + 1)
        return JobData(record, tuple(lines[-LOG_WINDOW:]), len(lines) > LOG_WINDOW)

    @property
    def job_log(self) -> JobLog:
        return self.query_one(JobLog)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != LOAD_GROUP:
            return
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, JobData):
            self.loaded_with(event.worker.result)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            body = self.query_one("#body")
            body.remove_children()
            body.mount(ErrorState("Couldn't load the job", describe_error(event.worker.error)))

    def loaded_with(self, data: JobData) -> None:
        self.gauntlet.flush_jobs()
        log = self.job_log
        log.set_log_path(data.record.log_path)
        log.write(((line, None) for line in data.lines), earlier=data.earlier)
        self.loaded = True
        self.show(data.record)
        pending, self.buffered = self.buffered, []
        fresh = [e.text for e in pending if e.kind == "line"]
        skip = overlap(data.lines, fresh)
        for event in pending:
            if event.kind == "line" and skip:
                skip -= 1
                continue
            self.apply([event])

    def on_job_events(self, events: tuple[JobEvent, ...]) -> None:
        mine = [e for e in events if e.record.id == self.job_id]
        if not mine:
            return
        if not self.loaded:
            self.buffered.extend(mine)
            return
        self.apply(mine)

    def apply(self, events: Sequence[JobEvent]) -> None:
        lines: deque[tuple[str, Stream | None]] = deque()
        for event in events:
            if event.kind == "line":
                lines.append((event.text, event.stream))
        if lines:
            self.job_log.write(lines)
        self.show(events[-1].record)

    def show(self, record: JobRecord) -> None:
        self.record = record
        if self.crumb != record.spec.title:
            self.crumb = record.spec.title
            self.refresh_chrome()
        self.query_one(JobHeader).show(record)
        self.query_one(Commands).show(record)
        finished = record.state in FINISHED
        outputs = self.query_one(Outputs)
        pane = self.query_one("#job-outputs")
        if finished and record.spec.outputs and not pane.display:
            outputs.set_options(
                [Option(output_line(o), id=str(i)) for i, o in enumerate(record.spec.outputs)]
            )
            pane.display = True
        if self._ticker is not None:
            if record.state == "running":
                self._ticker.resume()
            else:
                self._ticker.pause()
        self.update_log_title()
        self.refresh_bindings()

    def _tick(self) -> None:
        self.query_one(JobHeader).tick()

    def update_log_title(self) -> None:
        pane = self.query_one("#job-log")
        lines = self.query_one(LogLines)
        dot = self.gauntlet.look.glyphs.dot
        pane.border_title = f"Log {dot} {fmt.plural(lines.total, 'line')}"
        pane.border_subtitle = (
            "following · f stops" if lines.follow else "paused · f follows · G jumps to the end"
        )

    def on_log_lines_followed(self, _event: LogLines.Followed) -> None:
        self.update_log_title()
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        record = self.record
        if action == "cancel_job":
            return record is not None and record.state in ACTIVE
        if action == "open_output":
            return record is not None and record.state in FINISHED and bool(record.spec.outputs)
        if action == "filter":
            return self.loaded
        if action == "facets":
            return False
        return super().check_action(action, parameters)

    def action_filter(self) -> None:
        self.job_log.open_search()

    def action_toggle_follow(self) -> None:
        self.job_log.toggle_follow()

    def action_copy_commands(self) -> None:
        if (target := self.copy_target()) is not None:
            self.gauntlet.copy(*target)

    def copy_target(self) -> tuple[str, str] | None:
        if self.record is None:
            return None
        return "\n".join(command_line(step) for step in self.record.spec.steps), "commands"

    def action_cancel_job(self) -> None:
        record = self.record
        if record is None or record.state not in ACTIVE:
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self.cancel()

        question = f"Cancel {record.spec.title}?"
        self.app.push_screen(ConfirmPrompt(question, CANCEL_DETAIL, yes="Cancel it", no="Keep it"), answered)

    @work(thread=True, group="job-cancel", exit_on_error=False)
    def cancel(self) -> None:
        jobs = self.gauntlet.jobs
        if jobs is not None:
            try:
                jobs.cancel(self.job_id)
            except Exception as error:  # a job that just finished can't be cancelled; say so and move on
                self.app.call_from_thread(
                    self.notify, f"Couldn't cancel: {error}", severity="warning", markup=False
                )

    def action_open_output(self) -> None:
        record = self.record
        if record is None or not record.spec.outputs:
            return
        outputs = self.query_one(Outputs)
        if outputs.has_focus and outputs.highlighted is not None:
            self.gauntlet.open_output(record.spec.outputs[outputs.highlighted])
            return
        form = form_for(record.spec.action, self.gauntlet.actions)
        if record.state == "succeeded" and form is not None and form().after(record, self.gauntlet):
            return
        self.gauntlet.open_output(record.spec.outputs[0])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.record is not None and event.option.id is not None:
            event.stop()
            self.gauntlet.open_output(self.record.spec.outputs[int(event.option.id)])


@dataclass(frozen=True, slots=True)
class FileData:
    lines: tuple[str, ...]
    earlier: bool


class TextFileScreen(GauntletScreen):
    """A report or any text file a job wrote, as literal text. `/` searches it."""

    CSS_PATH = "job.tcss"

    def __init__(self, path: str, title: str) -> None:
        super().__init__()
        self.path = path
        self.crumb = title

    def compose_body(self) -> ComposeResult:
        pane = Vertical(JobLog(log_path=self.path), id="body", classes="pane")
        pane.border_title = self.crumb
        pane.border_subtitle = self.path
        yield pane

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(LogLines).follow = False
        self.query_one(LogLines).focus()
        self.run_worker(self.read, thread=True, group=LOAD_GROUP, exit_on_error=False)

    def read(self) -> FileData:
        with Path(self.path).open(encoding="utf-8", errors="replace") as handle:
            tail = deque(handle, maxlen=LOG_WINDOW + 1)
        lines = tuple(tail)
        return FileData(lines[-LOG_WINDOW:], len(lines) > LOG_WINDOW)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != LOAD_GROUP:
            return
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, FileData):
            data = event.worker.result
            self.query_one(JobLog).write(((line, None) for line in data.lines), earlier=data.earlier)
            self.query_one(LogLines).scroll_home(animate=False)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            body = self.query_one("#body")
            body.remove_children()
            body.mount(ErrorState(f"Couldn't read {self.crumb}", describe_error(event.worker.error)))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "filter":
            return bool(self.query(JobLog))
        if action == "facets":
            return False
        return super().check_action(action, parameters)

    def action_filter(self) -> None:
        self.query_one(JobLog).open_search()

    def copy_target(self) -> tuple[str, str] | None:
        return self.path, "path"
