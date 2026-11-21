"""A scripted `JobRunner` and builders for Workbench tests. Nothing here starts a process.

    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    record = runner.submit(spec)          # queued, like the real runner
    runner.start(record.id)               # running, step 1
    runner.line(record.id, "collecting")  # one log line on stdout
    runner.step(record.id, 1)             # step 2
    runner.finish(record.id, exit_code=0) # succeeded (non-zero: failed)

Each call emits the events the real runner would, to every listener, from the calling thread, or
from a fresh thread with `threaded=True`. `submitted` and `cancelled` record what the app asked
for. `form_app` mounts one form alone and `fill` sets its fields.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from textual.widgets import Input, Select, SelectionList, Switch

from gauntlet.tui.jobtypes import (
    FINISHED,
    JobEvent,
    JobNotFound,
    JobRecord,
    JobSpec,
    JobState,
    Listener,
    Machine,
    Output,
    Step,
    Stream,
    Unsubscribe,
)
from gauntlet.tui.models import DataSource
from gauntlet.tui.widgets.form import FieldRow, FormView
from gauntlet.tui.widgets.pickers import PathPicker, Picker
from gauntlet.tui.workbench.base import ActionForm

from .factories import WidgetApp, make_source

START = 1_763_800_000.0
SECOND = 1.0
GIB = 1024**3
FREE_DISK = 42 * GIB
WORKSPACE = "gauntlet-work"


def make_machine(**overrides: Any) -> Machine:
    values: dict[str, Any] = {
        "docker_running": True,
        "docker_detail": "Docker 27.3.1",
        "free_disk_bytes": FREE_DISK,
        "anthropic_key_set": False,
        "github_token_set": False,
        "workspace": WORKSPACE,
    }
    values.update(overrides)
    return Machine(**values)


def make_spec(**overrides: Any) -> JobSpec:
    values: dict[str, Any] = {
        "action": "calibrate",
        "title": "Calibrate live",
        "steps": (
            Step(
                "collect", ("collect", "--repo", "pallets/click", "-o", "gauntlet-work/tasks/click/prs.jsonl")
            ),
            Step("build", ("build", "--prs", "gauntlet-work/tasks/click/prs.jsonl")),
        ),
        "needs": ("docker",),
        "outputs": (Output("run", "gauntlet-work/runs/golden", "run golden"),),
    }
    values.update(overrides)
    return JobSpec(**values)


def make_record(job_id: str = "job-1", **overrides: Any) -> JobRecord:
    values: dict[str, Any] = {
        "id": job_id,
        "spec": make_spec(),
        "state": "queued",
        "created_at": START,
        "log_path": f"{WORKSPACE}/jobs/{job_id}/log.txt",
    }
    values.update(overrides)
    return JobRecord(**values)


class ScriptedRunner:
    """A `JobRunner` whose jobs only move when the test says so."""

    def __init__(
        self,
        machine: Machine | None = None,
        records: Iterable[JobRecord] = (),
        logs: dict[str, list[str]] | None = None,
        *,
        threaded: bool = False,
    ) -> None:
        self.machine_info = machine or make_machine()
        self.records: dict[str, JobRecord] = {r.id: r for r in records}
        self.logs: dict[str, list[str]] = {k: list(v) for k, v in (logs or {}).items()}
        self.listeners: list[Listener] = []
        self.submitted: list[JobSpec] = []
        self.cancelled: list[str] = []
        self.closed = False
        self.threaded = threaded
        self.clock = START + len(self.records)

    def machine(self) -> Machine:
        return self.machine_info

    def submit(self, spec: JobSpec) -> JobRecord:
        self.submitted.append(spec)
        job_id = f"job-{len(self.records) + 1}"
        self.clock += SECOND
        record = make_record(job_id, spec=spec, created_at=self.clock)
        self.records[job_id] = record
        self.logs[job_id] = []
        self._emit(JobEvent("state", record))
        return record

    def cancel(self, job_id: str) -> None:
        self.cancelled.append(job_id)
        if self.job(job_id).state not in FINISHED:
            self._move(job_id, state="cancelled", finished_at=self.clock + SECOND)

    def jobs(self) -> tuple[JobRecord, ...]:
        return tuple(self.records.values())

    def job(self, job_id: str) -> JobRecord:
        if job_id not in self.records:
            raise JobNotFound(job_id)
        return self.records[job_id]

    def log(self, job_id: str, *, tail: int | None = None) -> tuple[str, ...]:
        self.job(job_id)
        lines = self.logs.get(job_id, [])
        return tuple(lines[-tail:] if tail else lines)

    def subscribe(self, listener: Listener) -> Unsubscribe:
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener) if listener in self.listeners else None

    def close(self) -> None:
        self.closed = True

    def start(self, job_id: str) -> JobRecord:
        return self._move(job_id, state="running", started_at=self.clock, step_index=0)

    def step(self, job_id: str, index: int) -> JobRecord:
        record = replace(self.job(job_id), step_index=index)
        self.records[job_id] = record
        self._emit(JobEvent("step", record, text=record.spec.steps[index].title))
        return record

    def line(self, job_id: str, text: str, stream: Stream = "out") -> None:
        self.logs[job_id].append(text)
        self._emit(JobEvent("line", self.job(job_id), text=text, stream=stream))

    def lines(self, job_id: str, texts: Iterable[str], stream: Stream = "out") -> None:
        for text in texts:
            self.line(job_id, text, stream)

    def finish(self, job_id: str, *, exit_code: int = 0, seconds: float = 3 * SECOND) -> JobRecord:
        state: JobState = "succeeded" if exit_code == 0 else "failed"
        started = self.job(job_id).started_at or self.clock
        return self._move(job_id, state=state, exit_code=exit_code, finished_at=started + seconds)

    def _move(self, job_id: str, **changes: Any) -> JobRecord:
        record = replace(self.job(job_id), **changes)
        self.records[job_id] = record
        self._emit(JobEvent("state", record))
        return record

    def _emit(self, event: JobEvent) -> None:
        def send() -> None:
            for listener in list(self.listeners):
                listener(event)

        if self.threaded:
            thread = threading.Thread(target=send)
            thread.start()
            thread.join()
        else:
            send()


def finished_runner() -> ScriptedRunner:
    """One job in each finished state and one running, as an earlier session left them."""
    records = [
        make_record("job-1", state="succeeded", started_at=START, finished_at=START + 65, exit_code=0),
        make_record(
            "job-2",
            spec=make_spec(title="Scan fix.diff", action="scan", needs=(), exclusive=False, outputs=()),
            state="failed",
            created_at=START + 100,
            started_at=START + 100,
            finished_at=START + 102,
            exit_code=2,
        ),
        make_record(
            "job-3",
            state="cancelled",
            created_at=START + 200,
            started_at=START + 200,
            finished_at=START + 230,
        ),
    ]
    logs = {
        "job-1": ["calibrating on 3 task(s)", "77 episodes, 77 judged, 0 violation(s)"],
        "job-2": ['{"verdict": "cheating"}'],
        "job-3": ["calibrating on 3 task(s)"],
    }
    return ScriptedRunner(records=records, logs=logs)


def form_app(
    form: ActionForm, source: DataSource | None = None, *, workspace: Path | None = None
) -> WidgetApp:
    """One form alone in a bare app, for form tests."""
    data = source or make_source()
    return WidgetApp(FormView(form, source=lambda: data, workspace=workspace or Path(WORKSPACE), id="form"))


def fill(view: FormView, **values: object) -> None:
    """Set fields by name, the way typing or picking would."""
    for name, value in values.items():
        control = view.row(name).control
        if isinstance(control, Input):
            control.value = str(value)
        elif isinstance(control, PathPicker):
            control.input.value = str(value)
        elif isinstance(control, Picker):
            control.value = None if value is None else str(value)
        elif isinstance(control, Switch):
            control.value = bool(value)
        elif isinstance(control, Select):
            control.value = value
        elif isinstance(control, SelectionList):
            control.deselect_all()
            for item in value if isinstance(value, Iterable) else ():
                control.select(item)


def row_errors(view: FormView) -> dict[str, str]:
    return {row.field.name: row.note.error for row in view.query(FieldRow) if row.note.error is not None}


Script = Callable[[ScriptedRunner], None]
