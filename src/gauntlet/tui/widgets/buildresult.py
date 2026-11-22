"""`BuildResult`: what a finished "Make tasks" job built and why it rejected the rest, for the Job
screen's Result pane. The make-tasks forms return one from `ActionForm.outcome`.

The result reads the job's own files (see `buildfiles`), never its log: how many PRs or release
ranges went in, how many tasks came out, and each rejection grouped by the stage that turned it
away, with its PR number, title and the harness's reason. A build that keeps nothing exits 1, so
the job reads failed; the result says that's a normal outcome and why it happened.
"""

from __future__ import annotations

from functools import partial
from pathlib import Path

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..jobtypes import JobRecord, Output
from ..theme import ERROR, FAILED, PASSED, Look
from .buildfiles import RANGE_UNIT, BuildSummary, Item, read_build
from .states import describe_error
from .themed import Themed

NO_TASKS_EXIT = 1
ROWS_PEEK_BYTES = 4096
SHOWN_PER_GROUP = 8
GROUP_GAP = 1
RESULT_PANE = "#job-outcome"
READ_GROUP = "build-result"
COMMANDS = {"make_tasks": "gauntlet build", "make_lht_tasks": "gauntlet build-lht"}
STAGE_WORDS = {
    "collect": "couldn't fetch its commits",
    "filter": "not the kind of change a task is made from",
    "statement": "no problem statement it could use",
    "env": "its environment wouldn't build",
    "runs": "its test runs broke",
    "transitions": "the tests didn't show the fix doing its job",
    "leak": "failed a leak check, so an agent could find the answer",
    "crash": "the build hit an error on it",
}


def headline(record: JobRecord, summary: BuildSummary, look: Look) -> Text:
    unit = summary.unit
    asked = f" from {fmt.plural(summary.asked, unit)}" if summary.asked is not None else ""
    if unit != RANGE_UNIT and asked:
        asked += " collected"
    rejected = f", {len(summary.rejected):,} rejected" if summary.rejected else ""
    if record.spec.action == "make_tasks" and record.state == "failed" and record.step_index == 0:
        return Text.assemble(
            look.mark(ERROR, word=False),
            " Collecting PRs failed, so nothing was built. The log says why. A GitHub rate limit is "
            "the usual cause: set GITHUB_TOKEN, or turn on Git fallback.",
        )
    if summary.kept:
        text = Text.assemble(look.mark(PASSED, word=False), " ")
        text.append(fmt.plural(len(summary.kept), "task"), style="bold")
        text.append(f" built{asked}{rejected}.")
        return text
    if summary.missing and not summary.rejected:
        return Text.assemble(
            look.mark(ERROR, word=False),
            f" The build stopped before it wrote {', '.join(summary.missing)}. The log says why.",
        )
    if not summary.finished and summary.asked is not None:
        word = "was cancelled" if record.state == "cancelled" else "stopped"
        return Text.assemble(
            look.mark(ERROR, word=False),
            f" The build {word} after {summary.looked_at} of {fmt.plural(summary.asked, unit)}. "
            "What it got through is below.",
        )
    text = Text.assemble(look.mark(FAILED, word=False), " ")
    text.append("No task built", style="bold")
    text.append(f"{asked}{rejected}. That's a normal outcome, not an error.")
    return text


def item_rows(grid: Table, items: tuple[Item, ...], look: Look, *, reasons: bool) -> None:
    for item in items[:SHOWN_PER_GROUP]:
        grid.add_row(fmt.safe_text(item.name, single_line=True), fmt.safe_text(item.title, single_line=True))
        if reasons and item.reason:
            grid.add_row(Text(""), fmt.safe_text(item.reason, single_line=True, style=look.palette.muted))
    hidden = len(items) - SHOWN_PER_GROUP
    if hidden > 0:
        grid.add_row(Text(""), look.muted(f"and {hidden:,} more in the job's files"))


def group_title(label: str, count: int, words: str, look: Look) -> Text:
    text = Text(label, style="bold", end="")
    text.append(f"  {count:,}")
    if words:
        text.append_text(look.muted(f"  {words}"))
    return text


def summary_table(record: JobRecord, summary: BuildSummary, look: Look, note: str) -> Table:
    """The headline, the notes under it, then what was kept and each group of rejections."""
    table = Table.grid(expand=True)
    table.add_column(ratio=1)
    table.add_row(headline(record, summary, look))
    if summary.kept:
        table.add_row(look.muted("o opens the new task set."))
    command = COMMANDS.get(record.spec.action, "the build")
    nothing_kept = not summary.kept and summary.finished
    if nothing_kept and record.exit_code == NO_TASKS_EXIT:
        table.add_row(
            look.muted(
                f"{command} exits {NO_TASKS_EXIT} when it keeps no task, which is why the job reads failed."
            )
        )
    if note and (summary.rejected or nothing_kept):
        table.add_row(look.muted(note))
    if summary.skipped:
        table.add_row(look.muted(f"{fmt.plural(summary.skipped, 'line')} in its files couldn't be read."))
    groups: list[tuple[Text, tuple[Item, ...], bool]] = []
    if summary.kept:
        groups.append((group_title("Kept", len(summary.kept), "", look), summary.kept, False))
    for stage, items in summary.stages():
        title = group_title(f"Rejected at {stage}", len(items), STAGE_WORDS.get(stage, ""), look)
        groups.append((title, items, True))
    for title, items, reasons in groups:
        table.add_row(Text(""))
        table.add_row(title)
        grid = Table.grid(padding=(0, GROUP_GAP), expand=True)
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1, no_wrap=True, overflow=look.overflow)
        item_rows(grid, items, look, reasons=reasons)
        table.add_row(grid)
    return table


class BuildResult(Themed):
    """See the module docstring. Reads the job's files in a thread, then shows the summary."""

    DEFAULT_CSS = """
    BuildResult {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, record: JobRecord, *, note: str = "") -> None:
        super().__init__()
        self.record = record
        self.note = note
        self.summary: BuildSummary | None = None
        self.error: str | None = None

    def on_mount(self) -> None:
        super().on_mount()
        self.run_worker(
            partial(read_build, self.record.spec), thread=True, group=READ_GROUP, exit_on_error=False
        )

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != READ_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, BuildSummary):
            self.summary = event.worker.result
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.error = describe_error(event.worker.error)
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        if self.error is not None:
            return Text.assemble(
                look.mark(ERROR, word=False), f" Couldn't read what the job wrote: {self.error}"
            )
        if self.summary is None:
            return look.muted(f"Reading what the job wrote{look.glyphs.ellipsis}")
        return summary_table(self.record, self.summary, look, self.note)


def built_outputs(record: JobRecord) -> tuple[Output, ...]:
    """A build's outputs, without its task set when it kept no task, so `o` never opens an empty set."""
    return tuple(o for o in record.spec.outputs if o.kind != "tasks" or has_rows(Path(o.path)))


def has_rows(path: Path) -> bool:
    """Whether a `.jsonl` file is there and holds anything but blank lines. Reads one block."""
    if not path.is_file():
        return False
    with path.open("rb") as handle:
        return bool(handle.read(ROWS_PEEK_BYTES).strip())
