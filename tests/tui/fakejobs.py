"""Fakes for Workbench tests: `FakeJobRunner`, a scripted in-memory `JobRunner`, and
`fake_machine`, a `Machine` with friendly defaults.

Nothing here starts a process or a thread. A test says what a job prints and how it ends, then
moves the runner forward itself, so every event lands exactly when the test expects it.

    runner = FakeJobRunner()
    runner.script("make_tasks", ["collected 3 PRs", ("rate limited", "err")], exit_code=0)
    record = runner.submit(spec)            # queued: nothing has run yet
    runner.step()                           # starts it: a `state` event, then a `step` event
    runner.run_until_idle()                 # every line, then the end
    assert runner.job(record.id).state == "succeeded"

How the fake moves:

- `step()` makes one move and returns the events it sent, or `()` when nothing can move. A
  queued job that may start goes first, sending `state` (running) and `step` (its first step).
  Otherwise the oldest running job sends one scripted line, or a `step` event for a `NEXT_STEP`
  marker, or its end.
- Exclusive jobs start one at a time in the order they came in, like the real runner. Others
  start whenever `step()` reaches them.
- A script is chosen by the spec's `action`, and a job with no script prints nothing and
  succeeds. A non-zero `exit_code` that isn't in the current step's `ok_codes` ends it failed.
- `run_until_idle()` calls `step()` until nothing moves and returns every event.
- To drive one job by hand: `start(id)`, `emit(id, text, stream)`, `next_step(id)` and
  `finish(id, exit_code=..., error=...)`.
- `cancel(id)` ends a queued or running job as cancelled at once, and remembers the call in
  `cancel_requests`. `close()` sets `closed` and cancels whatever hasn't finished.
- `seed(spec, state=..., lines=...)` adds a finished job to the history, for list screens. A
  line is a string (stdout) or `(text, stream)`, as in a script.
  `seed(spec, state="failed", error=INTERRUPTED)` looks like a job from a session that closed.
- `submitted` holds every spec in order, and `machine_info` is what `machine()` returns: set
  it to `fake_machine(docker_running=False)` to test a missing need.
- Listeners are called in the test's own thread. One that raises is recorded in
  `listener_errors` and doesn't stop the others, like the real runner.
- The clock starts at `FAKE_START` and moves one second each time it's read.

For form tests: `form_app(form, workspace=...)` mounts one form alone, `fill(view, name=value)`
sets its fields the way typing or picking would, and `row_errors(view)` gives the error under
each field. `make_spec(**changes)` is a two step Docker job to run through the fake.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from textual.widgets import Input, Select, SelectionList, Switch

from gauntlet.tui.jobs import INTERRUPTED, RunnerClosed, format_job_id
from gauntlet.tui.jobtypes import (
    FINISHED,
    SUCCESS,
    JobEvent,
    JobNotFound,
    JobRecord,
    JobSpec,
    JobState,
    Listener,
    LogLine,
    Machine,
    Output,
    Step,
    Stream,
    Unsubscribe,
)
from gauntlet.tui.models import DataSource
from gauntlet.tui.widgets.form import FieldRow, FormView
from gauntlet.tui.widgets.pickers import PathPicker, Picker
from gauntlet.tui.workbench.base import ActionForm, action_info
from gauntlet.tui.workspace import Workspace

from .factories import WidgetApp, make_source

__all__ = [
    "INTERRUPTED",
    "NEXT_STEP",
    "FakeJobRunner",
    "Script",
    "fake_machine",
    "fill",
    "form_app",
    "make_spec",
    "row_errors",
]

FAKE_START = 1_795_000_000.0
FAKE_TICK = 1.0
FAKE_FREE_DISK = 50 * 1024**3
FAKE_WORKSPACE = "/fake/gauntlet-work"
NEXT_STEP = object()
"""Put this in a script's lines to move the job on to its next step."""

Line = str | tuple[str, Stream]


def fake_machine(**changes: object) -> Machine:
    """A machine where everything is ready: Docker up, 50 GB free, an API key set, no GitHub
    token. Pass any field to change it, for example `fake_machine(anthropic_key_set=False)`."""
    ready = Machine(
        docker_running=True,
        docker_detail="Docker 28.1.1 is running.",
        free_disk_bytes=FAKE_FREE_DISK,
        anthropic_key_set=True,
        github_token_set=False,
        workspace=FAKE_WORKSPACE,
    )
    return replace(ready, **changes)  # type: ignore[arg-type]  # fields are checked by replace


@dataclass(frozen=True)
class Script:
    """What a job prints, in order, and how it ends."""

    lines: tuple[Line | object, ...] = ()
    exit_code: int = SUCCESS
    error: str | None = None


@dataclass
class _Live:
    script: Script
    position: int = 0
    lines: list[str] = field(default_factory=list)
    streams: list[Stream | None] = field(default_factory=list)


class FakeJobRunner:
    """A `JobRunner` for tests. See the module docstring."""

    def __init__(self, *, machine: Machine | None = None) -> None:
        self.machine_info = machine or fake_machine()
        self.submitted: list[JobSpec] = []
        self.cancel_requests: list[str] = []
        self.listener_errors: list[Exception] = []
        self.closed = False
        self._scripts: dict[str, Script] = {}
        self._records: dict[str, JobRecord] = {}
        self._live: dict[str, _Live] = {}
        self._listeners: list[Listener] = []
        self._now = FAKE_START
        self._counter = 0

    # ------------------------------------------------------------------ scripting

    def script(
        self,
        action: str,
        lines: Iterable[Line | object] = (),
        *,
        exit_code: int = SUCCESS,
        error: str | None = None,
    ) -> None:
        """Every later job of this action prints `lines` and ends with `exit_code`."""
        self._scripts[action] = Script(tuple(lines), exit_code, error)

    def seed(
        self,
        spec: JobSpec,
        *,
        state: JobState = "succeeded",
        lines: Sequence[Line] = (),
        exit_code: int | None = SUCCESS,
        error: str | None = None,
    ) -> JobRecord:
        """A job already in the history, as if a past session ran it."""
        job_id = self._new_id()
        started = self._clock()
        record = JobRecord(
            id=job_id,
            spec=spec,
            state=state,
            created_at=started,
            log_path=f"{FAKE_WORKSPACE}/jobs/{job_id}/log.txt",
            step_index=max(len(spec.steps) - 1, 0),
            started_at=started,
            finished_at=self._clock() if state in FINISHED else None,
            exit_code=exit_code if state in FINISHED else None,
            error=error,
        )
        self._records[job_id] = record
        texts = [line if isinstance(line, str) else line[0] for line in lines]
        streams: list[Stream | None] = ["out" if isinstance(line, str) else line[1] for line in lines]
        self._live[job_id] = _Live(Script(), lines=texts, streams=streams)
        return record

    # ------------------------------------------------------------------ JobRunner

    def machine(self) -> Machine:
        return self.machine_info

    def submit(self, spec: JobSpec) -> JobRecord:
        if self.closed:
            raise RunnerClosed("the runner is closed and takes no more jobs")
        self.submitted.append(spec)
        job_id = self._new_id()
        record = JobRecord(
            id=job_id,
            spec=spec,
            state="queued",
            created_at=self._clock(),
            log_path=f"{FAKE_WORKSPACE}/jobs/{job_id}/log.txt",
        )
        self._records[job_id] = record
        self._live[job_id] = _Live(self._scripts.get(spec.action, Script()))
        self._emit(JobEvent("state", record))
        return record

    def cancel(self, job_id: str) -> None:
        record = self.job(job_id)
        self.cancel_requests.append(job_id)
        if record.state not in FINISHED:
            self._end(job_id, "cancelled")

    def jobs(self) -> tuple[JobRecord, ...]:
        """Every job, newest first, like the real runner."""
        return tuple(sorted(self._records.values(), key=lambda r: r.id, reverse=True))

    def job(self, job_id: str) -> JobRecord:
        try:
            return self._records[job_id]
        except KeyError:
            raise JobNotFound(f"no job {job_id!r}") from None

    def log(self, job_id: str, *, tail: int | None = None) -> tuple[str, ...]:
        self.job(job_id)
        lines = self._live[job_id].lines
        if tail is None:
            return tuple(lines)
        return tuple(lines[-tail:]) if tail > 0 else ()

    def log_lines(self, job_id: str, *, tail: int | None = None) -> tuple[LogLine, ...]:
        texts = self.log(job_id, tail=tail)
        streams = self._live[job_id].streams[len(self._live[job_id].lines) - len(texts) :]
        return tuple(LogLine(text, stream) for text, stream in zip(texts, streams, strict=True))

    def subscribe(self, listener: Listener) -> Unsubscribe:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def close(self) -> None:
        self.closed = True
        for record in list(self._records.values()):
            if record.state not in FINISHED:
                self._end(record.id, "cancelled")

    # ------------------------------------------------------------------ moving forward

    def step(self) -> tuple[JobEvent, ...]:
        """One move. A queued job that may start goes first, the way the real runner starts it at
        once; otherwise the oldest running job moves. `()` when nothing can."""
        ordered = sorted(self._records.values(), key=lambda r: r.id)
        for record in ordered:
            if record.state == "queued" and self._may_start(record):
                return self.start(record.id)
        for record in ordered:
            if record.state == "running":
                return self._advance(record.id)
        return ()

    def run_until_idle(self) -> tuple[JobEvent, ...]:
        """`step()` until nothing moves. Every event, in order."""
        events: list[JobEvent] = []
        while moved := self.step():
            events.extend(moved)
        return tuple(events)

    def start(self, job_id: str) -> tuple[JobEvent, ...]:
        """Start a queued job now, whatever the queue says."""
        record = self._set(job_id, state="running", started_at=self._clock(), step_index=0)
        first = (JobEvent("state", record), self._step_event(record))
        for event in first:
            self._emit(event)
        return first

    def emit(self, job_id: str, text: str, stream: Stream | None = "out") -> JobEvent:
        """Send one log line from a job."""
        self._live[job_id].lines.append(text)
        self._live[job_id].streams.append(stream)
        event = JobEvent("line", self.job(job_id), text=text, stream=stream)
        self._emit(event)
        return event

    def next_step(self, job_id: str) -> JobEvent:
        """Move a running job on to its next step."""
        record = self.job(job_id)
        record = self._set(job_id, step_index=min(record.step_index + 1, len(record.spec.steps) - 1))
        event = self._step_event(record)
        self._emit(event)
        return event

    def finish(self, job_id: str, *, exit_code: int = SUCCESS, error: str | None = None) -> JobEvent:
        """End a job the way the real runner would for this exit code."""
        record = self.job(job_id)
        steps = record.spec.steps
        ok = steps[record.step_index].ok_codes if steps else (SUCCESS,)
        if exit_code in ok:
            return self._end(job_id, "succeeded", exit_code=exit_code, error=error)
        title = steps[record.step_index].title if steps else "The job"
        return self._end(
            job_id, "failed", exit_code=exit_code, error=error or f"{title} exited with code {exit_code}"
        )

    # ------------------------------------------------------------------ inside

    def _may_start(self, record: JobRecord) -> bool:
        if not record.spec.exclusive:
            return True
        busy = any(r.state == "running" and r.spec.exclusive for r in self._records.values())
        first_waiting = min(
            (r.id for r in self._records.values() if r.state == "queued" and r.spec.exclusive), default=None
        )
        return not busy and first_waiting == record.id

    def _advance(self, job_id: str) -> tuple[JobEvent, ...]:
        live = self._live[job_id]
        if live.position < len(live.script.lines):
            item = live.script.lines[live.position]
            live.position += 1
            if item is NEXT_STEP:
                return (self.next_step(job_id),)
            text, stream = item if isinstance(item, tuple) else (item, "out")
            return (self.emit(job_id, str(text), stream),)
        return (self.finish(job_id, exit_code=live.script.exit_code, error=live.script.error),)

    def _step_event(self, record: JobRecord) -> JobEvent:
        title = record.spec.steps[record.step_index].title if record.spec.steps else ""
        return JobEvent("step", record, text=title)

    def _end(
        self, job_id: str, state: JobState, *, exit_code: int | None = None, error: str | None = None
    ) -> JobEvent:
        record = self._set(job_id, state=state, finished_at=self._clock(), exit_code=exit_code, error=error)
        event = JobEvent("state", record)
        self._emit(event)
        return event

    def _set(self, job_id: str, **changes: object) -> JobRecord:
        record = replace(self.job(job_id), **changes)  # type: ignore[arg-type]  # fields are checked by replace
        self._records[job_id] = record
        return record

    def _emit(self, event: JobEvent) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception as e:
                self.listener_errors.append(e)

    def _clock(self) -> float:
        now = self._now
        self._now += FAKE_TICK
        return now

    def _new_id(self) -> str:
        self._counter += 1
        return format_job_id(FAKE_START, self._counter)


def make_spec(**changes: object) -> JobSpec:
    """A two step Docker job that writes a run, like the ones the builders make."""
    spec = JobSpec(
        action="calibrate",
        title="Calibrate on live",
        steps=(
            Step(
                "Collect PRs",
                ("collect", "--repo", "pallets/click", "-o", f"{FAKE_WORKSPACE}/tasks/click/prs.jsonl"),
            ),
            Step("Build tasks", ("build", "--prs", f"{FAKE_WORKSPACE}/tasks/click/prs.jsonl")),
        ),
        needs=("docker", "network"),
        outputs=(Output("run", f"{FAKE_WORKSPACE}/runs/golden", "Calibration run"),),
    )
    return replace(spec, **changes)  # type: ignore[arg-type]  # fields are checked by replace


def form_app(
    form: ActionForm, source: DataSource | None = None, *, workspace: Path | None = None
) -> WidgetApp:
    """One form alone in a bare app, for form tests."""
    data = source or make_source()
    place = Workspace(workspace or FAKE_WORKSPACE)
    view = FormView(form, source=lambda: data, info=action_info(form.action_id), workspace=place, id="form")
    return WidgetApp(view)


def fill(view: FormView, **values: object) -> None:
    """Set fields by name, the way typing or picking would. A picker takes the choice's value."""
    for name, value in values.items():
        control = view.row(name).control
        if isinstance(control, Input):
            control.value = str(value)
        elif isinstance(control, PathPicker):
            control.input.value = str(value)
        elif isinstance(control, Picker):
            control.pick(next((c for c in control.fetch() if c.value == value), None))
        elif isinstance(control, Switch):
            control.value = bool(value)
        elif isinstance(control, Select):
            control.value = value
        elif isinstance(control, SelectionList):
            control.deselect_all()
            for item in value if isinstance(value, Iterable) else ():
                control.select(item)


def row_errors(view: FormView) -> dict[str, str]:
    """The error under each field that shows one, by field name."""
    return {row.field.name: row.note.error for row in view.query(FieldRow) if row.note.error is not None}
