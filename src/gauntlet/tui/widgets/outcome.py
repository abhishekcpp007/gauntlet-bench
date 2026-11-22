"""`OutcomeView`: what a finished scan or check found, read from its log in a thread. A scan's
verdict and each finding, or how many problems a check found, in the same marks the episode
screen uses. A scan or check form returns one from `ActionForm.outcome`. It posts `Read` with what
it found, so the Job screen can mark a check that found something, or hide the pane when a check
stopped without finding anything."""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.message import Message
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..actions import FINDING_MARKERS, FOUND_A_PROBLEM, Outcome, read_outcome
from ..jobtypes import JobRecord, JobRunner
from ..models import Finding
from ..theme import ERROR, FOUND, SEVERITIES, VERDICTS, Look
from .states import describe_error
from .themed import Themed

MARK_GAP = 1
READ_GROUP = "outcome-read"
NO_FINDINGS = "No rule fired. The patch looks like an honest fix."


def finding_lines(finding: Finding, look: Look) -> list[Text]:
    head = Text.assemble((finding.rule, "bold"), "  ", fmt.safe_text(finding.message, single_line=True))
    where = [
        part for part in (finding.file, f"step {finding.step}" if finding.step is not None else None) if part
    ]
    lines = [head]
    if where:
        lines.append(look.muted(f" {look.glyphs.dot} ".join(where)))
    if finding.evidence:
        lines.append(fmt.safe_text(finding.evidence, single_line=True, style=look.palette.muted))
    return lines


class OutcomeView(Themed):
    """See the module docstring."""

    DEFAULT_CSS = """
    OutcomeView {
        height: auto;
        padding: 0 1;
    }
    """

    class Read(Message):
        """The log was read. `outcome` is None when it held nothing to show."""

        def __init__(self, outcome: Outcome | None) -> None:
            super().__init__()
            self.outcome = outcome

    def __init__(self, record: JobRecord) -> None:
        super().__init__()
        self.record = record
        self.action = record.spec.action
        self.outcome: Outcome | None = None
        self.error: str | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self.run_worker(self.read, thread=True, group=READ_GROUP, exit_on_error=False)

    def read(self) -> Outcome | None:
        jobs: JobRunner | None = getattr(self.app, "jobs", None)
        if jobs is None:
            raise LookupError("the Workbench isn't on")
        return read_outcome(self.record, jobs.log(self.record.id))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != READ_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS:
            self.outcome = event.worker.result if isinstance(event.worker.result, Outcome) else None
            self.post_message(self.Read(self.outcome))
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.error = describe_error(event.worker.error)
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        outcome = self.outcome
        if self.error is not None:
            return Text.assemble(look.mark(ERROR, word=False), f" Couldn't read the job's log: {self.error}")
        if outcome is None:
            return look.muted(f"Reading the job's log{look.glyphs.ellipsis}")
        if outcome.scan_error is not None:
            return Text.assemble(look.mark(ERROR, word=False), " ", fmt.safe_text(outcome.scan_error))
        if outcome.scan is None:
            marker = FINDING_MARKERS.get(self.action, "").strip()
            problems = fmt.plural(outcome.found, "problem")
            return Text.assemble(
                look.mark(FOUND),
                f"  The check found {problems}. The lines that start with {marker} in the log say which.",
            )
        scan = outcome.scan
        grid = Table.grid(padding=(0, MARK_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        count = fmt.plural(len(scan.findings), "finding")
        grid.add_row(look.mark(VERDICTS[scan.verdict]), look.muted(count))
        if not scan.findings:
            grid.add_row(Text(""), look.muted(NO_FINDINGS))
        for finding in scan.findings:
            lines = finding_lines(finding, look)
            grid.add_row(look.mark(SEVERITIES[finding.severity]), lines[0])
            for line in lines[1:]:
                grid.add_row(Text(""), line)
        return grid


def check_outcome(record: JobRecord) -> OutcomeView | None:
    """For a check form's `outcome`: what it found, when it exited saying it found something."""
    found = record.state == "failed" and record.exit_code == FOUND_A_PROBLEM
    return OutcomeView(record) if found else None


def scan_outcome(record: JobRecord) -> OutcomeView | None:
    """For the scan form's `outcome`: the verdict and findings of a scan that finished."""
    return OutcomeView(record) if record.state == "succeeded" else None
