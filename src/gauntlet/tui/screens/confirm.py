"""The confirm steps: `ConfirmJob` before a job starts, and `ConfirmPrompt` for a yes or no.

`ConfirmJob` shows exactly what will happen: each command line as it'll run, what the job needs
and whether this machine has it, where the output goes, the free disk, and for a Docker job
whether it'll wait its turn. `enter` starts it, `esc` goes back to the form with the values kept.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Resize
from textual.screen import ModalScreen
from textual.widgets import Button

from .. import format as fmt
from ..jobtypes import JobSpec, Machine
from ..theme import NEED_MISSING, NEED_UNCHECKED, PASSED, WARNING, Look
from ..widgets.jobstatus import command_line, disk_size
from ..widgets.themed import Themed
from ..workbench.base import check_needs

LABEL_GAP = 2
CONFIRM_CHROME_ROWS = 8
"""Rows around the plan: the frame, its padding, the buttons and their margin, and a row each
above and below the box."""
MIN_PLAN_ROWS = 3
PROMPT = "$ "


def plan_lines(spec: JobSpec, machine: Machine | None, *, waits: bool, look: Look) -> Table:
    """Each command line, what it needs, where it writes, the free disk and the queue."""
    grid = Table.grid(padding=(0, LABEL_GAP), expand=True)
    grid.add_column(no_wrap=True)
    grid.add_column(ratio=1, overflow="fold")
    steps = spec.steps
    for index, step in enumerate(steps):
        label = "Runs" if index == 0 else ""
        line = Text.assemble(look.muted(PROMPT), fmt.safe_text(command_line(step)))
        title = look.muted(f"{index + 1}. {step.title}" if len(steps) > 1 else step.title)
        grid.add_row(look.muted(label), title)
        grid.add_row(Text(""), line)
    grid.add_row(Text(""), Text(""))
    if spec.needs:
        checks = check_needs(spec.needs, machine) if machine is not None else ()
        for index, check in enumerate(checks):
            mark = PASSED if check.met else NEED_UNCHECKED if check.met is None else NEED_MISSING
            line = Text.assemble(look.mark(mark, word=False), (f" {check.label}", "bold"))
            line.append_text(look.muted(f"  {check.detail}"))
            grid.add_row(look.muted("Needs" if index == 0 else ""), line)
    else:
        grid.add_row(look.muted("Needs"), Text("nothing but this machine", end=""))
    for index, output in enumerate(spec.outputs):
        line = Text.assemble(fmt.safe_text(output.path), look.muted(f"  ({output.kind})"))
        grid.add_row(look.muted("Writes" if index == 0 else ""), line)
    if machine is not None:
        grid.add_row(look.muted("Free disk"), Text(disk_size(machine.free_disk_bytes), end=""))
    if spec.exclusive:
        if waits:
            line = Text.assemble(
                look.mark(WARNING, word=False),
                " Another Docker job is running, so this one waits its turn in the queue.",
            )
        else:
            line = look.muted("Docker jobs run one at a time. Nothing else is running, so this starts now.")
        grid.add_row(look.muted("Queue"), line)
    return grid


class JobPlan(Themed):
    """What the job will do, as a block of labelled lines."""

    DEFAULT_CSS = """
    JobPlan {
        height: auto;
    }
    """

    def __init__(self, spec: JobSpec, machine: Machine | None, *, waits: bool) -> None:
        super().__init__()
        self.spec = spec
        self.machine = machine
        self.waits = waits

    def render(self) -> RenderableType:
        return plan_lines(self.spec, self.machine, waits=self.waits, look=self.look)


class ConfirmJob(ModalScreen[bool]):
    """Start this job? `enter` starts it, `esc` goes back."""

    BINDINGS = [
        Binding("escape", "answer(False)", "Back"),
        Binding("enter", "answer(True)", "Start", priority=True),
    ]

    def __init__(self, spec: JobSpec, machine: Machine | None, *, waits: bool = False) -> None:
        super().__init__()
        self.spec = spec
        self.machine = machine
        self.waits = waits

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box", classes="confirm-box") as box:
            box.border_title = f"Start {self.spec.title}?"
            box.border_subtitle = "enter starts it · esc goes back"
            with VerticalScroll(classes="confirm-plan", can_focus=False):
                yield JobPlan(self.spec, self.machine, waits=self.waits)
            with Horizontal(classes="confirm-actions"):
                yield Button("Start", variant="primary", id="start", compact=True)
                yield Button("Back", id="back", compact=True)

    def on_mount(self) -> None:
        self.query_one("#start", Button).focus()
        self.fit(self.app.size.height)

    def on_resize(self, event: Resize) -> None:
        self.fit(event.size.height)

    def fit(self, height: int) -> None:
        """Let the plan scroll, so a long plan never pushes Start off the screen."""
        self.query_one(".confirm-plan").styles.max_height = max(height - CONFIRM_CHROME_ROWS, MIN_PLAN_ROWS)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "start")

    def action_answer(self, start: bool) -> None:
        on_back = self.focused is not None and self.focused.id == "back"
        self.dismiss(start and not on_back)


class PromptText(Themed):
    DEFAULT_CSS = """
    PromptText {
        height: auto;
        margin-bottom: 1;
    }
    """

    def __init__(self, question: str, detail: str) -> None:
        super().__init__()
        self.question = question
        self.detail = detail

    def render(self) -> RenderableType:
        text = Text(self.question, style="bold", end="")
        if self.detail:
            text.append("\n")
            text.append_text(self.look.muted(self.detail))
        return text


class ConfirmPrompt(ModalScreen[bool]):
    """A yes or no. `y` or `enter` says yes, `n` or `esc` says no."""

    BINDINGS = [
        Binding("y", "answer(True)", "Yes"),
        Binding("n,escape", "answer(False)", "No"),
    ]

    def __init__(self, question: str, detail: str = "", *, yes: str = "Yes", no: str = "No") -> None:
        super().__init__()
        self.question = question
        self.detail = detail
        self.yes = yes
        self.no = no

    def compose(self) -> ComposeResult:
        with Vertical(classes="confirm-box prompt-box") as box:
            box.border_title = "Are you sure?"
            box.border_subtitle = "y yes · n no"
            yield PromptText(self.question, self.detail)
            with Horizontal(classes="confirm-actions"):
                yield Button(self.yes, variant="error", id="yes", compact=True)
                yield Button(self.no, id="no", compact=True)

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(event.button.id == "yes")

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
