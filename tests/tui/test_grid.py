from textual.app import ComposeResult

from gauntlet.tui.models import TaskRow
from gauntlet.tui.theme import leak_mark
from gauntlet.tui.widgets import Column, CopyRequested, DataGrid, Empty
from gauntlet.tui.widgets.grid import GridTable

from .factories import TASK_ROWS, WidgetApp, make_task_row, screen_text

COLUMNS: tuple[Column[TaskRow], ...] = (
    Column("id", "Instance", lambda t: t.instance_id, kind="id", shrink=True),
    Column("dataset", "Dataset", lambda t: t.dataset_id, priority=3),
    Column("repo", "Repo", lambda t: t.repo, priority=2),
    Column("f2p", "F2P", lambda t: t.f2p, kind="number", priority=4),
    Column("merged", "Merged", lambda t: t.merged_at, kind="date", priority=5),
    Column("leak", "Leak", lambda t: leak_mark(t.leakcheck_ok), kind="mark", priority=2),
)


class GridApp(WidgetApp):
    def __init__(self, rows=TASK_ROWS, **kwargs) -> None:
        self.grid: DataGrid[TaskRow] = DataGrid(
            COLUMNS, key=lambda t: t.instance_id, empty=Empty("No tasks loaded.", "Try --datasets."), **kwargs
        )
        self.grid.set_rows(rows)
        super().__init__(self.grid)
        self.opened: list[str] = []
        self.copied: list[tuple[str, str]] = []

    def compose(self) -> ComposeResult:
        yield self.grid

    def on_data_grid_opened(self, event: DataGrid.Opened) -> None:
        self.opened.append(event.key)

    def on_copy_requested(self, event: CopyRequested) -> None:
        self.copied.append((event.text, event.what))


async def test_rows_render_with_typed_cells():
    app = GridApp()
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        table = app.grid.table
        assert table.row_count == len(TASK_ROWS)
        assert app.grid.visible_columns == ("id", "dataset", "repo", "f2p", "merged", "leak")
        text = screen_text(app)
        assert "hukkin__tomli-318" in text
        assert "2026-10-06" in text
        assert "✓ ok" in text


async def test_enter_opens_and_c_copies_the_row_key():
    app = GridApp(what="instance id")
    async with app.run_test(size=(140, 24)) as pilot:
        app.grid.focus_table()
        await pilot.press("j", "enter")
        assert app.opened == [TASK_ROWS[1].instance_id]
        await pilot.press("c")
        assert app.copied == [(TASK_ROWS[1].instance_id, "instance id")]
        await pilot.press("G")
        assert app.grid.current_key == TASK_ROWS[-1].instance_id
        await pilot.press("g")
        assert app.grid.current_key == TASK_ROWS[0].instance_id


async def test_s_cycles_the_sort_and_S_flips_it():
    rows = (make_task_row(instance_id="b", f2p=1), make_task_row(instance_id="a", f2p=5))
    app = GridApp(rows=rows)
    async with app.run_test(size=(140, 24)) as pilot:
        app.grid.focus_table()
        await pilot.press("s")
        assert app.grid.sort is not None and app.grid.sort.key == "id" and not app.grid.sort.reverse
        assert app.grid.current_key == "b"
        assert app.grid.table.get_row_at(0)[0].plain == "a"
        await pilot.press("S")
        assert app.grid.table.get_row_at(0)[0].plain == "b"
        for _ in COLUMNS[1:]:
            await pilot.press("s")
        assert app.grid.sort is not None and app.grid.sort.key == "leak"
        await pilot.press("s")
        assert app.grid.sort is None


async def test_numbers_sort_largest_first():
    rows = (make_task_row(instance_id="b", f2p=1), make_task_row(instance_id="a", f2p=5))
    app = GridApp(rows=rows)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        app.grid.sort_by("f2p", reverse=True)
        assert [app.grid.table.get_row_at(i)[0].plain for i in range(2)] == ["a", "b"]
        header = str(app.grid.table.columns[app.grid.table.columns.__iter__().__next__()].label)
        assert header == "Instance"


async def test_cursor_stays_on_its_key_when_rows_are_replaced():
    app = GridApp()
    async with app.run_test(size=(140, 24)) as pilot:
        app.grid.focus_table()
        await pilot.press("j", "j", "j")
        key = app.grid.current_key
        app.grid.set_rows(tuple(reversed(TASK_ROWS)))
        await pilot.pause()
        assert app.grid.current_key == key
        assert app.grid.current is not None and app.grid.current.instance_id == key


async def test_narrow_width_drops_columns_by_priority_and_cuts_ids():
    app = GridApp()
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        wide = app.grid.visible_columns
        await pilot.resize_terminal(40, 24)
        await pilot.pause()
        narrow = app.grid.visible_columns
        assert "id" in narrow and len(narrow) < len(wide)
        assert "merged" not in narrow
        text = screen_text(app)
        assert "more-it…" in text or "…" in text
        assert all(len(line) <= 40 for line in text.splitlines())


async def test_empty_grid_says_why():
    app = GridApp(rows=())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert app.grid.has_class("-empty")
        text = screen_text(app)
        assert "No tasks loaded." in text and "Try --datasets." in text
        app.grid.set_rows((), empty=Empty("No tasks match.", "Press esc to clear the filter."))
        await pilot.pause()
        assert "No tasks match." in screen_text(app)
        app.grid.set_rows(TASK_ROWS[:1])
        await pilot.pause()
        assert not app.grid.has_class("-empty")


async def test_untrusted_cells_render_literally():
    rows = (make_task_row(instance_id="x", repo="[red]boom[/red]\x1b[2J"),)
    app = GridApp(rows=rows)
    async with app.run_test(size=(140, 24)) as pilot:
        await pilot.pause()
        assert "[red]boom[/red]^[[2J" in screen_text(app)


async def test_footer_bindings_are_declared():
    keys = {b.key for b in GridTable.BINDINGS} | {b.key for b in DataGrid.BINDINGS}
    assert {"enter", "j", "k", "g", "G", "s", "S", "c"} <= keys
