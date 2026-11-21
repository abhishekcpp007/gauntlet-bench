"""`Matrix`: tasks down the side, policies across the top, each cell a reward.

    matrix = Matrix(source.matrix(run_id))

Each cell prints the reward on the diverging scale with its sign and two decimals, then a mark
for resolved, a cheating or suspicious verdict, and tampering, so colour is never the only
signal. A pair that wasn't played shows a dim dot. The task column stays put while the policies
scroll sideways. Arrow keys and `hjkl` move the cursor, `enter` posts `Matrix.Opened` with the
cell's episode id and `c` copies it. A legend and a status line naming the focused cell in full
sit under the grid. It knows nothing about runs: give it any `models.Matrix`.
"""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.message import Message
from textual.widgets import DataTable

from .. import format as fmt
from ..models import Matrix as MatrixData
from ..models import MatrixCell
from ..theme import (
    RESOLVED,
    REWARD_MAX,
    REWARD_MIN,
    TAMPERED,
    VERDICTS,
    Look,
    Mark,
    resolved_mark,
    tamper_mark,
)
from .messages import CopyRequested
from .themed import Themed

NOT_PLAYED = Mark("·", ".", "not played", "muted")
FIRST_POLICY = 1
GAP = " "
HEADER_WIDTH = 9
MARK_SLOTS = 2
CELL_WIDTH = len(fmt.reward(REWARD_MIN)) + len(GAP) + MARK_SLOTS
POLICY_WIDTH = len(GAP) + max(CELL_WIDTH, HEADER_WIDTH)
MIN_TASK_WIDTH = 16
SCROLLBAR_WIDTH = 1
LEGEND_GAP = "  "


def short_policy(policy: str, ellipsis: str = fmt.ELLIPSIS) -> str:
    """`cheater:canary-aware` as `canary-aw…`: the part after the last colon, cut at the end."""
    name = policy.rsplit(":", 1)[-1]
    if len(name) <= HEADER_WIDTH:
        return name
    return name[: HEADER_WIDTH - len(ellipsis)] + ellipsis


def cell_marks(cell: MatrixCell) -> list[Mark]:
    """What a cell flags besides its reward: resolved, a verdict that isn't clean, tampering."""
    marks: list[Mark] = []
    if cell.resolved:
        marks.append(RESOLVED)
    if cell.verdict != "clean":
        marks.append(VERDICTS[cell.verdict])
    if cell.tampered:
        marks.append(TAMPERED)
    return marks


def render_cell(cell: MatrixCell | None, look: Look) -> Text:
    if cell is None:
        return Text(GAP, end="") + look.mark(NOT_PLAYED, word=False)
    text = Text(GAP, end="")
    text.append_text(look.reward(cell.reward))
    text.append(GAP)
    marks = cell_marks(cell)
    for mark in marks:
        text.append_text(look.mark(mark, word=False))
    text.append(" " * max(MARK_SLOTS - len(marks), 0))
    return text


class MatrixTable(DataTable[Text]):
    """The grid inside a `Matrix`. The cursor never rests on the task column."""

    HELP_GROUP = "Matrix"
    BINDINGS = [
        Binding("enter", "select_cursor", "Open"),
        Binding("h", "cursor_left", "Left", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("l", "cursor_right", "Right", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
    ]

    def validate_cursor_coordinate(self, value: Coordinate) -> Coordinate:
        value = super().validate_cursor_coordinate(value)
        if value.column < FIRST_POLICY and len(self.columns) > FIRST_POLICY:
            return Coordinate(value.row, FIRST_POLICY)
        return value


class Legend(Themed):
    """What each mark means, and the reward scale from -1 to +1. `not played` shows only when
    some pair wasn't played."""

    DEFAULT_CSS = """
    Legend {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, *, missing: bool) -> None:
        super().__init__()
        self.missing = missing

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="", no_wrap=True, overflow="ellipsis")
        marks = [RESOLVED, VERDICTS["cheating"], VERDICTS["suspicious"], TAMPERED]
        if self.missing:
            marks.append(NOT_PLAYED)
        for mark in marks:
            text.append_text(look.mark(mark))
            text.append(LEGEND_GAP)
        text.append_text(look.muted(f"reward{GAP}"))
        for value in (REWARD_MIN, 0.0, REWARD_MAX):
            text.append_text(look.reward(value))
            text.append(GAP)
        return text


class CellStatus(Themed):
    """The focused cell in full: task, policy, reward, resolved, verdict and tampering."""

    DEFAULT_CSS = """
    CellStatus {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.task_id = ""
        self.policy_name = ""
        self.cell: MatrixCell | None = None

    def show(self, task: str, policy: str, cell: MatrixCell | None) -> None:
        self.task_id, self.policy_name, self.cell = task, policy, cell
        self.refresh()

    def render(self) -> RenderableType:
        look = self.look
        if not self.task_id:
            return ""
        sep = look.muted(f"  {look.glyphs.dot}  ")
        text = Text(end="")
        text.append_text(fmt.safe_text(self.task_id, single_line=True, style="bold"))
        text.append_text(sep)
        text.append_text(look.accent(self.policy_name))
        text.append_text(sep)
        cell = self.cell
        if cell is None:
            text.append_text(look.mark(NOT_PLAYED))
            return text
        text.append_text(look.reward(cell.reward, bold=True))
        for mark in (resolved_mark(cell.resolved), VERDICTS[cell.verdict]):
            text.append_text(sep)
            text.append_text(look.mark(mark))
        if cell.tampered is not None:
            text.append_text(sep)
            text.append_text(look.mark(tamper_mark(cell.tampered)))
        return text


class Matrix(Themed):
    """A tasks by policies reward grid with a legend and a status line. See the module docstring."""

    DEFAULT_CSS = """
    Matrix {
        height: 1fr;
    }
    Matrix > MatrixTable {
        height: 1fr;
        background: $surface;
        scrollbar-size-vertical: 1;
        scrollbar-size-horizontal: 1;
    }
    Matrix > MatrixTable > .datatable--header {
        color: $foreground-muted;
        background: $surface;
        text-style: bold;
    }
    Matrix > MatrixTable > .datatable--fixed {
        background: $surface;
    }
    Matrix > MatrixTable > .datatable--header-cursor,
    Matrix > MatrixTable > .datatable--header-hover {
        color: $text-primary;
        background: $surface;
    }
    Matrix > CellStatus {
        border-top: solid $border-blurred;
        max-height: 3;
    }
    App.-ascii Matrix > CellStatus {
        border-top: ascii $border-blurred;
    }
    """

    HELP_GROUP = "Matrix"
    BINDINGS = [Binding("c", "copy", "Copy episode id")]

    class Opened(Message):
        """`enter` on a played cell. The screen opens the episode."""

        def __init__(self, matrix: Matrix, episode_id: str) -> None:
            super().__init__()
            self.matrix = matrix
            self.episode_id = episode_id

        @property
        def control(self) -> Matrix:
            return self.matrix

    def __init__(self, data: MatrixData, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.data = data
        self._width = 0

    def compose(self) -> ComposeResult:
        yield MatrixTable(cursor_type="cell", fixed_columns=FIRST_POLICY, cell_padding=0)
        yield CellStatus()
        yield Legend(missing=any(cell is None for row in self.data.cells for cell in row))

    @property
    def table(self) -> MatrixTable:
        return self.query_one(MatrixTable)

    @property
    def coordinate(self) -> tuple[int, int] | None:
        """`(task index, policy index)` under the cursor, or None when the grid is empty."""
        table = self.table
        if not table.row_count or len(table.columns) <= FIRST_POLICY:
            return None
        row, column = table.cursor_coordinate
        return row, column - FIRST_POLICY

    @property
    def current(self) -> MatrixCell | None:
        where = self.coordinate
        return None if where is None else self.data.cells[where[0]][where[1]]

    def on_mount(self) -> None:
        super().on_mount()
        self._rebuild()

    def on_theme_change(self) -> None:
        self._rebuild()

    def on_resize(self) -> None:
        if self._task_width() != self._width:
            self._rebuild()

    def _task_width(self) -> int:
        """Wide enough for the longest task id if there's room, so every policy fits on screen."""
        longest = max((len(t.instance_id) for t in self.data.tasks), default=0) + len(GAP)
        room = self.size.width - SCROLLBAR_WIDTH - POLICY_WIDTH * len(self.data.policies)
        return max(MIN_TASK_WIDTH, min(longest, room))

    def _rebuild(self) -> None:
        look = self.look
        table = self.table
        keep = table.cursor_coordinate
        self._width = width = self._task_width()
        with self.app.batch_update():
            table.clear(columns=True)
            table.add_column(Text(f"{GAP}Task", end=""), width=width, key="task")
            for policy in self.data.policies:
                label = GAP + short_policy(policy, look.glyphs.ellipsis)
                table.add_column(Text(label, end=""), width=POLICY_WIDTH, key=policy)
            for task, cells in zip(self.data.tasks, self.data.cells, strict=True):
                name = GAP + fmt.middle(fmt.visible(task.instance_id), width - len(GAP), look.glyphs.ellipsis)
                table.add_row(
                    Text(name, end=""), *(render_cell(c, look) for c in cells), key=task.instance_id
                )
            if table.row_count:
                table.move_cursor(row=keep.row, column=max(keep.column, FIRST_POLICY), animate=False)
        self._show_status()

    def _show_status(self) -> None:
        where = self.coordinate
        status = self.query_one(CellStatus)
        if where is None:
            status.show("", "", None)
            return
        row, column = where
        status.show(self.data.tasks[row].instance_id, self.data.policies[column], self.current)

    def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        event.stop()
        self._show_status()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        event.stop()
        if (cell := self.current) is not None:
            self.post_message(self.Opened(self, cell.episode_id))

    def action_copy(self) -> None:
        if (cell := self.current) is not None:
            self.post_message(CopyRequested(cell.episode_id, "episode id"))
