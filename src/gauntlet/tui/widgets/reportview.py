"""`ReportView`: the Markdown that `gauntlet report` prints, drawn as real tables. And
`ReportScreen`, which shows a finished report job's leaderboard.

`parse_report` reads the printed lines into blocks: headings, tables, bullets and paragraphs.
Every cell is untrusted text, so it's drawn literally. Number columns are right-aligned.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar

from rich import box
from rich.console import RenderableType
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import ScrollableContainer, Vertical, VerticalScroll
from textual.geometry import Size
from textual.widget import Widget
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..jobtypes import LogLine
from ..screens.base import GauntletScreen
from ..theme import Look
from .states import ErrorState, describe_error
from .themed import Themed

CELL_EDGE = "|"
RULE_CELL = set("-: ")
HEADING = "#"
BULLET = "- "
STRONG = "**"
NO_VALUE = "-"
CELL_GAP = 2
LOAD_GROUP = "report-load"
WIDEST_TABLE = 10_000
NO_REPORT = "The report printed no table. The job's log says why."


@dataclass(frozen=True, slots=True)
class Heading:
    text: str


@dataclass(frozen=True, slots=True)
class ReportTable:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Bullet:
    text: str


@dataclass(frozen=True, slots=True)
class Paragraph:
    text: str


Block = Heading | ReportTable | Bullet | Paragraph


def cells(line: str) -> tuple[str, ...]:
    """`| a | b |` as `("a", "b")`."""
    inner = line.strip()
    inner = inner.removeprefix(CELL_EDGE).removesuffix(CELL_EDGE)
    return tuple(cell.strip() for cell in inner.split(CELL_EDGE))


def is_rule(row: Sequence[str]) -> bool:
    return all(cell and set(cell) <= RULE_CELL for cell in row)


def parse_report(lines: Sequence[str]) -> tuple[Block, ...]:
    """The blocks of a printed report. Blank lines end a paragraph or a table."""
    blocks: list[Block] = []
    table: list[tuple[str, ...]] = []
    paragraph: list[str] = []

    def close() -> None:
        if table:
            body = tuple(row for row in table[1:] if not is_rule(row))
            blocks.append(ReportTable(table[0], body))
            table.clear()
        if paragraph:
            blocks.append(Paragraph(" ".join(paragraph)))
            paragraph.clear()

    for raw in lines:
        line = raw.rstrip("\r\n").strip()
        if not line:
            close()
        elif line.startswith(CELL_EDGE):
            if paragraph:
                close()
            table.append(cells(line))
        elif line.startswith(HEADING):
            close()
            blocks.append(Heading(line.lstrip(HEADING).strip()))
        elif line.startswith(STRONG) and line.endswith(STRONG) and len(line) > len(STRONG) * 2:
            close()
            blocks.append(Heading(line[len(STRONG) : -len(STRONG)]))
        elif line.startswith(BULLET):
            close()
            blocks.append(Bullet(line.removeprefix(BULLET)))
        else:
            if table:
                close()
            paragraph.append(line)
    close()
    return tuple(blocks)


def is_number(value: str) -> bool:
    if value == NO_VALUE:
        return True
    try:
        float(value)
    except ValueError:
        return False
    return True


def draw_table(table: ReportTable, look: Look) -> Table:
    grid = Table(
        box=box.ASCII if look.ascii else box.SIMPLE_HEAD,
        border_style=look.style("muted"),
        header_style="bold",
        padding=(0, 1),
        pad_edge=False,
        show_edge=False,
    )
    width = len(table.header)
    for index, name in enumerate(table.header):
        column = [row[index] for row in table.rows if index < len(row)]
        numeric = bool(column) and index > 0 and all(is_number(cell) for cell in column)
        grid.add_column(
            fmt.safe_text(name, single_line=True), justify="right" if numeric else "left", no_wrap=True
        )
    for row in table.rows:
        padded = (*row, *([""] * (width - len(row))))[:width]
        grid.add_row(*(styled_cell(cell, look) for cell in padded))
    return grid


def styled_cell(cell: str, look: Look) -> Text:
    if cell == NO_VALUE:
        return look.muted(fmt.MISSING)
    return fmt.safe_text(cell, single_line=True)


def draw_block(block: Block | None, look: Look) -> RenderableType:
    """One block. None is the line for a report that printed no table."""
    if block is None:
        return look.muted(NO_REPORT)
    if isinstance(block, Heading):
        return look.accent(fmt.one_line(block.text), bold=True)
    if isinstance(block, ReportTable):
        return draw_table(block, look)
    if isinstance(block, Bullet):
        line = look.muted(f"{look.glyphs.bullet} ")
        line.append_text(fmt.safe_text(block.text, single_line=True))
        return line
    return fmt.safe_text(block.text, single_line=True, style=look.palette.muted)


class BlockView(Themed):
    """One block of a report. A table keeps its own width; the rest wrap to the pane."""

    DEFAULT_CSS = """
    BlockView {
        height: auto;
    }
    BlockView.-table {
        width: auto;
    }
    """

    def __init__(self, block: Block | None) -> None:
        super().__init__(classes="-table" if isinstance(block, ReportTable) else "")
        self.block = block

    def get_content_width(self, container: Size, viewport: Size) -> int:
        if not isinstance(self.block, ReportTable):
            return super().get_content_width(container, viewport)
        console = self.app.console
        options = console.options.update_width(WIDEST_TABLE)
        return Measurement.get(console, options, draw_table(self.block, self.look)).maximum

    def render(self) -> RenderableType:
        return draw_block(self.block, self.look)


class TableScroll(ScrollableContainer):
    """A table that's wider than the pane scrolls sideways instead of cutting its numbers."""

    DEFAULT_CSS = """
    TableScroll {
        height: auto;
        overflow-x: auto;
        overflow-y: hidden;
    }
    """


class ReportView(Vertical):
    """A printed report, drawn: a heading, a table or a line per block, a blank line between."""

    DEFAULT_CSS = """
    ReportView {
        height: auto;
        padding: 0 1;
    }
    ReportView > * {
        margin-bottom: 1;
    }
    """

    def __init__(self, blocks: Sequence[Block] = ()) -> None:
        super().__init__()
        self.blocks = tuple(blocks)

    def compose(self) -> ComposeResult:
        yield from self.views()

    def views(self) -> list[Widget]:
        shown: list[Widget] = [
            TableScroll(BlockView(b)) if isinstance(b, ReportTable) else BlockView(b) for b in self.blocks
        ]
        if not any(isinstance(b, ReportTable) for b in self.blocks):
            shown.append(BlockView(None))
        return shown

    def show(self, blocks: Sequence[Block]) -> None:
        self.blocks = tuple(blocks)
        self.remove_children()
        self.mount_all(self.views())


def report_lines(lines: Sequence[LogLine]) -> tuple[str, ...]:
    """What the report printed: its stdout, without warnings on stderr."""
    return tuple(line.text for line in lines if line.stream != "err")


class ReportScreen(GauntletScreen):
    """The leaderboard a report job printed, as tables. `esc` goes back to the job."""

    crumb = "Leaderboard"

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    DEFAULT_CSS = """
    ReportScreen #report-body {
        height: 1fr;
        padding: 1 1 0 1;
    }
    """

    def __init__(self, job_id: str, title: str) -> None:
        super().__init__()
        self.job_id = job_id
        self.title_text = title

    def compose_body(self) -> ComposeResult:
        body = VerticalScroll(ReportView(), id="report-body", classes="pane")
        body.border_title = self.title_text
        body.border_subtitle = (
            f"job {self.job_id} {self.gauntlet.look.glyphs.dot} tab, then arrows, scroll a wide table"
        )
        yield body

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one("#report-body").focus()
        self.run_worker(self.read, thread=True, group=LOAD_GROUP, exit_on_error=False)

    def read(self) -> tuple[Block, ...]:
        jobs = self.gauntlet.jobs
        if jobs is None:
            raise LookupError("the Workbench isn't on")
        return parse_report(report_lines(jobs.log_lines(self.job_id)))

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != LOAD_GROUP:
            return
        if event.state == WorkerState.SUCCESS and isinstance(event.worker.result, tuple):
            self.query_one(ReportView).show(event.worker.result)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            body = self.query_one("#report-body")
            body.remove_children()
            body.mount(ErrorState("Couldn't read the report", describe_error(event.worker.error)))

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ("filter", "facets"):
            return False
        return super().check_action(action, parameters)

    def action_scroll_home(self) -> None:
        self.query_one("#report-body", VerticalScroll).scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        self.query_one("#report-body", VerticalScroll).scroll_end(animate=False)
