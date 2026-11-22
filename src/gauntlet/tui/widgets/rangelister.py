"""`RangeLister`: the first half of "From a release range", inside the form itself.

A button lists the repo's release ranges with `gauntlet ranges`, after the same confirm step every
job gets, and the job runs while the form stays where it is. A status line says what's happening:
listing (with a spinner), how many ranges it found, that the repo has none, or why it failed. When
the listing ends, its ranges fill the form's range field, so picking them and building them is the
same form. "Open its log" opens the listing job's screen.

Listing only needs the network (or nothing, for a local clone), so it isn't blocked when Docker is
down, though the build is.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal

from rich.console import RenderableType
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.timer import Timer
from textual.widgets import Button
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..actions import ActionError, ReleaseRange, list_ranges, parse_ranges
from ..jobtypes import FINISHED, JobEvent, JobRecord, JobSpec
from ..theme import ERROR, PASSED, WARNING
from ..workbench.base import Choice, blocked_reason
from .form import FormView
from .jobstatus import SPINNER_FPS, job_mark
from .states import describe_error
from .themed import Themed

if TYPE_CHECKING:
    from ..app import GauntletApp

State = Literal["idle", "listing", "found", "none", "failed", "cancelled", "refused"]
READ_GROUP = "range-log"
REPO_FLAG = "--repo"
URL_FLAG = "--repo-url"
PRERELEASE_FLAG = "--prereleases"
LIST_BUTTON = "list-ranges"
LOG_BUTTON = "ranges-log"
IDLE = "Lists the repo's release ranges. It clones the repo, so it needs the network but not Docker."
NO_RUNNER = "There's no job runner here, so the ranges can't be listed."
PRERELEASE_TIP = " Turn on Prereleases to count rc, alpha and beta tags too."

Listed = Callable[[str, str | None, tuple[ReleaseRange, ...]], None]
"""Told the repo, the clone URL and the ranges each time a listing ends with ranges (or none)."""


@dataclass(frozen=True, slots=True)
class ListFields:
    """The names of the form's fields the lister reads, and the one it fills."""

    repo: str
    repo_url: str
    last: str
    prereleases: str
    ranges: str


def flag_value(argv: tuple[str, ...], flag: str) -> str | None:
    """The value after `flag` in a command line, or None when it isn't there."""
    return argv[argv.index(flag) + 1] if flag in argv[:-1] else None


def range_choices(ranges: tuple[ReleaseRange, ...]) -> tuple[Choice, ...]:
    """One choice a range, `FROM..TO` as its value, its tags and counts lined up as its label."""
    if not ranges:
        return ()
    width_a = max(len(r.from_ref) for r in ranges)
    width_b = max(len(r.to_ref) for r in ranges)
    width_prs = max(len(fmt.plural(r.prs, "PR")) for r in ranges)
    out = []
    for r in ranges:
        line = (
            f"{fmt.one_line(r.from_ref):<{width_a}}  to  {fmt.one_line(r.to_ref):<{width_b}}  "
            f"{fmt.plural(r.prs, 'PR'):>{width_prs}}, {fmt.plural(r.direct_commits, 'direct commit')}"
        )
        out.append(Choice(r.spec, line))
    return tuple(out)


class ListerStatus(Themed):
    """What the listing is doing, in one or two lines."""

    DEFAULT_CSS = """
    ListerStatus {
        height: auto;
        width: 1fr;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.state: State = "idle"
        self.message = IDLE
        self.frame = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._timer = self.set_interval(1 / SPINNER_FPS, self._spin, pause=True)

    def _spin(self) -> None:
        self.frame += 1
        self.refresh()

    def show(self, state: State, message: str) -> None:
        self.state = state
        self.message = message
        if self._timer is not None:
            if state == "listing":
                self._timer.resume()
            else:
                self._timer.pause()
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="")
        if self.state == "listing":
            text.append_text(job_mark(look, "running", frame=self.frame, word=False))
            text.append(" ")
        elif self.state == "found":
            text.append_text(look.mark(PASSED, word=False))
            text.append(" ")
        elif self.state == "none":
            text.append_text(look.mark(WARNING, word=False))
            text.append(" ")
        elif self.state in ("failed", "refused"):
            text.append_text(look.mark(ERROR, word=False))
            text.append(" ")
        if self.state in ("idle", "cancelled"):
            text.append_text(look.muted(self.message))
        else:
            text.append_text(fmt.safe_text(self.message))
        return text


class RangeLister(Vertical):
    """See the module docstring. `view` is the form it reads and fills, `listed` hears each result."""

    SCOPED_CSS = False
    DEFAULT_CSS = """
    RangeLister {
        height: auto;
        margin: 0 0 1 20;
        max-width: 84;
    }
    FormView.-stacked RangeLister {
        margin-left: 0;
    }
    RangeLister > Horizontal {
        height: auto;
    }
    RangeLister Button {
        margin-right: 1;
    }
    """

    def __init__(self, view: FormView, fields: ListFields, listed: Listed) -> None:
        super().__init__(id="range-lister")
        self.view = view
        self.fields = fields
        self.listed = listed
        self.job_id: str | None = None
        self.spec: JobSpec | None = None

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Button("List ranges", id=LIST_BUTTON, compact=True)
            log = Button("Open its log", id=LOG_BUTTON, compact=True)
            log.display = False
            yield log
        yield ListerStatus()

    @property
    def status(self) -> ListerStatus:
        return self.query_one(ListerStatus)

    @property
    def gauntlet(self) -> GauntletApp | None:
        from ..app import GauntletApp

        return self.app if isinstance(self.app, GauntletApp) else None

    def on_mount(self) -> None:
        app = self.gauntlet
        if app is not None:
            app.job_events.subscribe(self, self.on_job_events)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if event.button.id == LIST_BUTTON:
            self.ask()
        elif event.button.id == LOG_BUTTON and self.job_id is not None and self.gauntlet is not None:
            self.gauntlet.open_job(self.job_id)

    def checked(self) -> dict[str, object] | None:
        """The repo, clone URL, newest and prereleases fields, checked, or None after focusing a bad one."""
        values: dict[str, object] = {}
        fields = self.fields
        for name in (fields.repo, fields.repo_url, fields.last, fields.prereleases):
            row = self.view.row(name)
            ok, value = row.validate()
            if not ok:
                row.focus_control()
                return None
            values[name] = value
        return values

    def ask(self) -> None:
        """Check the fields, build the listing job and show its confirm step."""
        values = self.checked()
        if values is None:
            return
        fields = self.fields
        last = values[fields.last]
        try:
            spec = list_ranges(
                str(values[fields.repo]),
                repo_url=None if values[fields.repo_url] is None else str(values[fields.repo_url]),
                last=None if last is None else int(str(last)),
                prereleases=bool(values[fields.prereleases]),
            )
        except ActionError as error:
            self.status.show("refused", str(error))
            return
        app = self.gauntlet
        if app is None or app.jobs is None:
            self.status.show("refused", NO_RUNNER)
            return
        machine = getattr(self.screen, "machine", None)
        if machine is not None and (reason := blocked_reason(spec.needs, machine)):
            self.status.show("refused", reason)
            return
        from ..screens.confirm import ConfirmJob

        def answered(start: bool | None) -> None:
            if start:
                self.submit(spec)

        app.push_screen(ConfirmJob(spec, machine), answered)

    @work(thread=True, group="range-submit", exit_on_error=False)
    def submit(self, spec: JobSpec) -> None:
        app = self.gauntlet
        if app is None or app.jobs is None:
            return
        try:
            record = app.jobs.submit(spec)
        except Exception as error:  # a refused job gets one line, and the form keeps its values
            self.app.call_from_thread(self.status.show, "failed", f"Couldn't start: {describe_error(error)}")
            return
        self.app.call_from_thread(self.started, spec, record)

    def started(self, spec: JobSpec, record: JobRecord) -> None:
        app = self.gauntlet
        self.job_id = record.id
        self.spec = spec
        self.query_one(f"#{LOG_BUTTON}").display = True
        repo = flag_value(spec.steps[0].argv, REPO_FLAG)
        self.status.show(
            "listing", f"Listing the ranges of {repo}. It clones the repo first, which can take a minute."
        )
        if app is not None:
            app.remember_job(record)
            self.follow(app.job_records.get(record.id, record))

    def on_job_events(self, events: tuple[JobEvent, ...]) -> None:
        for event in events:
            if event.record.id == self.job_id:
                self.follow(event.record)

    def follow(self, record: JobRecord) -> None:
        if record.id != self.job_id or record.state not in FINISHED:
            return
        if record.state == "cancelled":
            self.status.show("cancelled", "Listing was cancelled. Press List ranges to try again.")
        elif record.state == "failed":
            why = record.error or f"exit {record.exit_code}"
            self.status.show("failed", f"Listing failed: {why}. Open its log to see why.")
        else:
            self.read(record)

    def read(self, record: JobRecord) -> None:
        app = self.gauntlet
        if app is None or app.jobs is None:
            return
        self.run_worker(partial(app.jobs.log, record.id), thread=True, group=READ_GROUP, exit_on_error=False)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != READ_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, tuple):
            self.found(parse_ranges([str(line) for line in event.worker.result]))
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.status.show(
                "failed", f"Couldn't read the listing's log: {describe_error(event.worker.error)}"
            )

    def found(self, ranges: tuple[ReleaseRange, ...]) -> None:
        spec = self.spec
        if spec is None:
            return
        argv = spec.steps[0].argv
        repo = flag_value(argv, REPO_FLAG) or ""
        url = flag_value(argv, URL_FLAG)
        row = self.view.row(self.fields.ranges)
        row.set_choices(range_choices(ranges))
        self.listed(repo, url, ranges)
        if not ranges:
            tip = "" if PRERELEASE_FLAG in argv else PRERELEASE_TIP
            self.status.show(
                "none",
                f"{repo} has no release ranges. A range needs two release tags, one built on the other.{tip}",
            )
            return
        found = fmt.plural(len(ranges), "range")
        self.status.show("found", f"{found} of {repo}. Pick the ones to build under Ranges.")
        row.focus_control()
