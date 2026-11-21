"""`JobStatus`, and the words and marks the Workbench uses for jobs and the machine.

`theme.py` keeps its marks as module constants with no way to add more, so the job states live
here as `Mark`s in the same vocabulary: running is the accent with a spinner, succeeded a green
check, failed a red cross, cancelled and queued dim. Colour is never the only signal.
"""

from __future__ import annotations

import shlex
import time

from rich.console import RenderableType
from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer

from .. import format as fmt
from ..jobtypes import FINISHED, JobRecord, JobState, Step
from ..theme import Look, Mark
from .themed import Themed

JOB_MARKS: dict[JobState, Mark] = {
    "queued": Mark("◌", "-", "queued", "muted"),
    "running": Mark("●", "*", "running", "accent"),
    "succeeded": Mark("✓", "+", "succeeded", "good"),
    "failed": Mark("✗", "x", "failed", "bad"),
    "cancelled": Mark("⊘", "/", "cancelled", "muted"),
}
ACTIVE: frozenset[JobState] = frozenset({"queued", "running"})
SPINNER_FPS = 8
BYTES_PER_UNIT = 1024
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB")
SIZE_DIGITS = 1
GIGABYTE = BYTES_PER_UNIT ** SIZE_UNITS.index("GB")
PROGRAM = "gauntlet"


def job_mark(look: Look, state: JobState, *, frame: int | None = None, word: bool = True) -> Text:
    """The state as symbol and word. A running job shows spinner frame `frame` when one is given."""
    mark = JOB_MARKS[state]
    if state == "running" and frame is not None:
        frames = look.glyphs.spinner
        text = Text(frames[frame % len(frames)], style=look.style(mark.tone), end="")
        if word:
            text.append(f" {mark.word}", style=look.style(mark.tone))
        return text
    return look.mark(mark, word=word)


def command_line(step: Step) -> str:
    """The step exactly as a person would type it: `gauntlet collect --repo owner/name`."""
    return shlex.join((PROGRAM, *step.argv))


def elapsed(record: JobRecord, now: float | None = None) -> float | None:
    """Seconds the job has run, up to now or to when it finished. None before it starts."""
    if record.started_at is None:
        return None
    end = record.finished_at if record.finished_at is not None else (time.time() if now is None else now)
    return max(end - record.started_at, 0.0)


def step_line(record: JobRecord) -> str:
    """`step 2 of 2: build`, for the step running now or the last one that ran."""
    steps = record.spec.steps
    if not steps:
        return "no steps"
    index = min(max(record.step_index, 0), len(steps) - 1)
    return f"step {index + 1} of {len(steps)}: {steps[index].title}"


def result_line(record: JobRecord) -> str:
    """`exit 0 after 3 m 05 s`, or what happened instead. Empty while the job hasn't finished."""
    if record.state not in FINISHED:
        return ""
    took = fmt.duration(elapsed(record))
    if record.state == "cancelled":
        return f"cancelled after {took}"
    code = fmt.MISSING if record.exit_code is None else str(record.exit_code)
    line = f"exit {code} after {took}"
    return f"{line}: {record.error}" if record.error else line


def disk_size(free: int) -> str:
    """`12.3 GB`, in powers of 1024."""
    value = float(free)
    unit = SIZE_UNITS[0]
    for unit in SIZE_UNITS:
        if value < BYTES_PER_UNIT or unit == SIZE_UNITS[-1]:
            break
        value /= BYTES_PER_UNIT
    return f"{value:.0f} {unit}" if unit == SIZE_UNITS[0] else f"{value:.{SIZE_DIGITS}f} {unit}"


class JobStatus(Themed):
    """A job's state as symbol and word, like `✓ succeeded`. Spins while the job runs."""

    DEFAULT_CSS = """
    JobStatus {
        width: auto;
        height: 1;
    }
    """

    state: reactive[JobState] = reactive("queued", layout=True)

    def __init__(self, state: JobState, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.set_reactive(JobStatus.state, state)
        self._frame = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self._timer = self.set_interval(1 / SPINNER_FPS, self._spin, pause=self.state != "running")

    def watch_state(self, state: JobState) -> None:
        if self._timer is not None:
            if state == "running":
                self._timer.resume()
            else:
                self._timer.pause()

    def _spin(self) -> None:
        self._frame += 1
        self.refresh()

    def render(self) -> RenderableType:
        return job_mark(self.look, self.state, frame=self._frame)
