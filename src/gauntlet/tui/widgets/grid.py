"""`DataGrid`: a typed table over `DataTable`, with column priority, sorting and an empty state.

    columns = [
        Column("id", "Instance", lambda t: t.instance_id, kind="id"),
        Column("repo", "Repo", lambda t: t.repo, priority=2),
        Column("f2p", "F2P", lambda t: t.f2p, kind="number", priority=3),
    ]
    grid = DataGrid(columns, key=lambda t: t.instance_id, empty=Empty("No tasks loaded."))
    grid.set_rows(rows)

`enter` posts `DataGrid.Opened` with the row, `c` posts `CopyRequested` with the row's key, and
`s` cycles the sort (`S` flips it). When the grid is too narrow, columns with the largest
`priority` drop first and the `shrink` column is cut in the middle. Rows keep the cursor on the
same key when they're replaced.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

from rich.cells import cell_len
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.events import Resize
from textual.message import Message
from textual.widgets import DataTable

from .. import format as fmt
from ..theme import Look, Mark
from .messages import CopyRequested
from .states import Empty, EmptyState
from .themed import Themed

R = TypeVar("R")
ColumnKind = Literal["text", "id", "number", "reward", "date", "mark"]

CELL_PADDING = 1
CELL_SIDES = 2
MIN_SHRINK_WIDTH = 8
SCROLLBAR_WIDTH = 1

NUMERIC_KINDS: frozenset[ColumnKind] = frozenset({"number", "reward"})
DESCENDING_FIRST: frozenset[ColumnKind] = frozenset({"number", "reward", "date"})
ESSENTIAL = 1
NOTHING = Empty("Nothing to show.")


@dataclass(frozen=True, slots=True)
class Column(Generic[R]):
    """One column. `value` gives the raw value, used to sort and, unless `render` is set, to show.

    `kind` picks the default rendering: `id` and `text` literally, `number` right-aligned with
    thousands separators, `reward` on the diverging scale, `date` as `2026-11-05`, and `mark`
    (a `theme.Mark`) as symbol and word. `priority` 1 never drops; larger numbers drop first.
    """

    key: str
    label: str
    value: Callable[[R], Any]
    kind: ColumnKind = "text"
    priority: int = ESSENTIAL
    width: int | None = None
    shrink: bool = False
    render: Callable[[R, Look], Text] | None = None
    sortable: bool = True


@dataclass(frozen=True, slots=True)
class Sort:
    key: str
    reverse: bool


_QUIET = (
    ("left", "cursor_left"),
    ("right", "cursor_right"),
    ("home", "scroll_home"),
    ("end", "scroll_end"),
    ("ctrl+pageup", "page_left"),
    ("ctrl+pagedown", "page_right"),
)


class GridTable(DataTable[Text]):
    """The `DataTable` inside a `DataGrid`, with the viewer's keys."""

    HELP_GROUP = "List"
    BINDINGS = [
        Binding("enter", "select_cursor", "Open"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("g", "scroll_top", "Top", show=False),
        Binding("G", "scroll_bottom", "Bottom", show=False),
        Binding("pageup", "page_up", "Page up", show=False),
        Binding("pagedown", "page_down", "Page down", show=False),
        *(Binding(key, action, "", show=False) for key, action in _QUIET),
    ]


def _sort_key(value: Any) -> tuple[int, Any]:
    if value is None:
        return (1, 0)
    if isinstance(value, Mark):
        return (0, value.word)
    if isinstance(value, bool):
        return (0, int(value))
    return (0, value)


class DataGrid(Themed, Generic[R]):
    """A table of records of one type. See the module docstring for an example."""

    DEFAULT_CSS = """
    DataGrid {
        height: 1fr;
    }
    DataGrid > GridTable {
        height: 1fr;
        background: $surface;
        scrollbar-size-vertical: 1;
    }
    DataGrid > GridTable > .datatable--header {
        color: $foreground-muted;
        background: $surface;
        text-style: bold;
    }
    DataGrid > EmptyState {
        display: none;
    }
    DataGrid.-empty > GridTable {
        display: none;
    }
    DataGrid.-empty > EmptyState {
        display: block;
    }
    """

    HELP_GROUP = "List"
    BINDINGS = [
        Binding("s", "sort_next", "Sort"),
        Binding("S", "sort_flip", "Reverse sort", show=False),
        Binding("c", "copy", "Copy id"),
    ]

    class Opened(Message):
        """`enter` (or a click) on a row. `row` is the record the row was built from."""

        def __init__(self, grid: DataGrid[Any], key: str, row: Any) -> None:
            super().__init__()
            self.grid = grid
            self.key = key
            self.row = row

        @property
        def control(self) -> DataGrid[Any]:
            return self.grid

    def __init__(
        self,
        columns: Sequence[Column[R]],
        *,
        key: Callable[[R], str],
        empty: Empty = NOTHING,
        what: str = "id",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.columns: tuple[Column[R], ...] = tuple(columns)
        self.row_key = key
        self.empty = empty
        self.what = what
        self.sort: Sort | None = None
        self._rows: tuple[R, ...] = ()
        self._by_key: dict[str, R] = {}
        self._layout: tuple[tuple[Column[R], int], ...] = ()

    def compose(self) -> ComposeResult:
        yield GridTable(cursor_type="row", zebra_stripes=False, cell_padding=CELL_PADDING)
        yield EmptyState(self.empty)

    @property
    def table(self) -> GridTable:
        return self.query_one(GridTable)

    @property
    def rows(self) -> tuple[R, ...]:
        return self._rows

    @property
    def visible_columns(self) -> tuple[str, ...]:
        return tuple(column.key for column, _ in self._layout)

    @property
    def current_key(self) -> str | None:
        table = self.table
        if not table.row_count:
            return None
        return str(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    @property
    def current(self) -> R | None:
        key = self.current_key
        return None if key is None else self._by_key.get(key)

    def set_rows(self, rows: Sequence[R], *, empty: Empty | None = None) -> None:
        """Replace every row in one batch. The cursor stays on the same key if it's still there."""
        if empty is not None:
            self.empty = empty
        self._rows = tuple(rows)
        self._by_key = {self.row_key(row): row for row in self._rows}
        self._rebuild()

    def sort_by(self, key: str | None, *, reverse: bool = False) -> None:
        self.sort = None if key is None else Sort(key, reverse)
        self._rebuild()

    def focus_table(self) -> None:
        self.table.focus()

    def on_theme_change(self) -> None:
        self._rebuild()

    def on_resize(self, event: Resize) -> None:
        if self._plan(self._available()) != self._layout:
            self._rebuild()

    def action_sort_next(self) -> None:
        sortable = [c for c in self.columns if c.sortable and c.key in self.visible_columns]
        if not sortable:
            return
        keys = [c.key for c in sortable]
        if self.sort is None:
            following = 0
        else:
            following = keys.index(self.sort.key) + 1 if self.sort.key in keys else 0
        if following >= len(keys):
            self.sort_by(None)
            return
        column = sortable[following]
        self.sort_by(column.key, reverse=column.kind in DESCENDING_FIRST)

    def action_sort_flip(self) -> None:
        if self.sort is not None:
            self.sort_by(self.sort.key, reverse=not self.sort.reverse)

    def action_copy(self) -> None:
        if (key := self.current_key) is not None:
            self.post_message(CopyRequested(key, self.what))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        event.stop()
        key = str(event.row_key.value)
        if key in self._by_key:
            self.post_message(self.Opened(self, key, self._by_key[key]))

    def _ordered(self) -> list[R]:
        rows = list(self._rows)
        if self.sort is not None:
            column = next((c for c in self.columns if c.key == self.sort.key), None)
            if column is not None:
                present = [r for r in rows if column.value(r) is not None]
                missing = [r for r in rows if column.value(r) is None]
                present.sort(key=lambda r: _sort_key(column.value(r)), reverse=self.sort.reverse)
                rows = present + missing
        return rows

    def _cell(self, column: Column[R], row: R, look: Look) -> Text:
        if column.render is not None:
            return column.render(row, look)
        value = column.value(row)
        if column.kind == "reward":
            return look.reward(value)
        if column.kind == "mark":
            return look.mark(value) if isinstance(value, Mark) else look.muted(fmt.MISSING)
        if value is None:
            return look.muted(fmt.MISSING)
        if column.kind == "number":
            return Text(fmt.count(value) if isinstance(value, int) else str(value), end="")
        if column.kind == "date":
            return Text(fmt.date(value), end="")
        return fmt.safe_text(value, single_line=True)

    def _natural_width(self, column: Column[R], look: Look) -> int:
        if column.width is not None:
            return column.width
        header = cell_len(column.label) + cell_len(look.glyphs.descending) + 1
        widest = max((self._cell(column, row, look).cell_len for row in self._rows), default=0)
        return max(header, widest)

    def _available(self) -> int:
        return max(self.size.width - SCROLLBAR_WIDTH, 0)

    def on_mount(self) -> None:
        self._rebuild()

    def _plan(self, available: int) -> tuple[tuple[Column[R], int], ...]:
        """Which columns fit in `available` cells and how wide each is.

        Essential columns always show. The rest go in by priority, each one only if it still
        fits, so a wide low-priority column never pushes out a narrow one. Then the `shrink`
        column gives up width if the essentials alone are too wide.
        """
        look = self.look
        widths = {c.key: self._natural_width(c, look) + CELL_SIDES * CELL_PADDING for c in self.columns}
        chosen = {c.key for c in self.columns if c.priority <= ESSENTIAL}
        used = sum(widths[k] for k in chosen)
        for column in sorted(self.columns, key=lambda c: c.priority):
            if column.key in chosen:
                continue
            if not available or used + widths[column.key] <= available:
                chosen.add(column.key)
                used += widths[column.key]
        shown = [c for c in self.columns if c.key in chosen]
        over = used - available if available else 0
        for column in shown:
            if over > 0 and column.shrink:
                cut = min(over, widths[column.key] - MIN_SHRINK_WIDTH - CELL_SIDES * CELL_PADDING)
                widths[column.key] -= max(cut, 0)
                break
        widths = {k: w - CELL_SIDES * CELL_PADDING for k, w in widths.items()}
        return tuple((c, widths[c.key]) for c in shown)

    def _label(self, column: Column[R], look: Look) -> Text:
        label = column.label
        if self.sort is not None and self.sort.key == column.key:
            arrow = look.glyphs.descending if self.sort.reverse else look.glyphs.ascending
            label = f"{label} {arrow}"
        return Text(label, justify="right" if column.kind in NUMERIC_KINDS else "left", end="")

    def _fit(self, text: Text, column: Column[R], width: int, look: Look) -> Text:
        if column.kind in NUMERIC_KINDS:
            text.justify = "right"
        if text.cell_len > width:
            if column.kind in ("id", "text"):
                return Text(fmt.middle(text.plain, width, look.glyphs.ellipsis), style=text.style, end="")
            text.truncate(width, overflow="ellipsis")
        return text

    def _rebuild(self) -> None:
        if not self.is_mounted:
            return
        look = self.look
        table = self.table
        keep = self.current_key
        self._layout = self._plan(self._available())
        self.set_class(not self._rows, "-empty")
        self.query_one(EmptyState).show(self.empty)
        with self.app.batch_update():
            table.clear(columns=True)
            for column, width in self._layout:
                table.add_column(self._label(column, look), width=width, key=column.key)
            for row in self._ordered():
                cells = [self._fit(self._cell(c, row, look), c, w, look) for c, w in self._layout]
                table.add_row(*cells, key=self.row_key(row))
            if keep is not None and keep in self._by_key:
                table.move_cursor(row=table.get_row_index(keep), animate=False)
