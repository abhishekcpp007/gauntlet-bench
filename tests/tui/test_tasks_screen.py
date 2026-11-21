from textual.coordinate import Coordinate
from textual.widgets import OptionList

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.task import TaskScreen
from gauntlet.tui.screens.tasks import TasksScreen, TaskTable
from gauntlet.tui.widgets import FacetPicker, FilterBar

from .factories import LHT, TASK_ROWS, empty_source, failing_source, make_source, screen_text

WIDE = (140, 40)
SMALL = (80, 24)
KEY_COLUMNS = {"id", "repo", "f2p", "leak"}


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_tasks(app: GauntletApp, pilot) -> TaskTable:
    await pilot.press("2")
    await settle(app, pilot)
    assert isinstance(app.screen, TasksScreen)
    return app.screen.query_one(TaskTable)


def first_key(table: TaskTable) -> str:
    grid = table.grid.table
    return str(grid.coordinate_to_cell_key(Coordinate(0, 0)).row_key.value)


async def test_every_task_shows_with_its_columns():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        assert len(table.grid.rows) == len(TASK_ROWS)
        assert set(table.grid.visible_columns) >= KEY_COLUMNS | {"merged", "n2p", "p2p"}
        text = screen_text(app)
        assert "Tasks · 12" in text
        assert "12 of 12" in text
        assert "hukkin__tomli-318" in text
        assert "✓ ok" in text


async def test_slash_filters_as_you_type_and_esc_clears():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.press("slash", *"boltons")
        await settle(app, pilot)
        assert {r.repo for r in table.grid.rows} == {"mahmoud/boltons"}
        assert "2 of 12" in screen_text(app)
        await pilot.press("escape")
        await settle(app, pilot)
        assert len(table.grid.rows) == len(TASK_ROWS)


async def test_filter_matches_pr_titles():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.press("slash", *"sparse arrays")
        await settle(app, pilot)
        assert [r.instance_id for r in table.grid.rows] == ["sveltejs__devalue-191"]


async def test_no_match_says_how_to_get_rows_back():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_tasks(app, pilot)
        await pilot.press("slash", *"nothing-like-this")
        await settle(app, pilot)
        text = screen_text(app)
        assert "No task matches." in text
        assert "0 of 12" in text


async def test_f_picks_a_facet_with_counts():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FacetPicker)
        picker = app.screen.query_one(OptionList)
        assert "gauntlet-lht-2026-11  3" in screen_text(app)
        picker.highlighted = picker.get_option_index(f"dataset\0{LHT}")
        await pilot.press("enter")
        await settle(app, pilot)
        assert {r.dataset_id for r in table.grid.rows} == {LHT}
        text = screen_text(app)
        assert f"dataset {LHT}" in text
        assert "3 of 12" in text


async def test_facets_and_query_combine():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        table.bar.set_facet("runner", "vitest")
        await settle(app, pilot)
        assert len(table.grid.rows) == 3
        await pilot.press("slash", *"exsolve")
        await settle(app, pilot)
        assert [r.instance_id for r in table.grid.rows] == ["unjs__exsolve-80"]


async def test_s_cycles_the_sort():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.press("s")
        await pilot.pause()
        assert table.grid.sort is not None and table.grid.sort.key == "id"
        assert first_key(table) == min(r.instance_id for r in TASK_ROWS)
        await pilot.press("s")
        await pilot.pause()
        assert table.grid.sort is not None and table.grid.sort.key == table.grid.visible_columns[1]


async def test_enter_opens_the_task():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_tasks(app, pilot)
        await pilot.press("j", "enter")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen)
        assert app.screen.instance_id == TASK_ROWS[1].instance_id


async def test_c_copies_the_instance_id():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_tasks(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == TASK_ROWS[0].instance_id


async def test_cursor_and_filter_survive_opening_a_task():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.press("slash", *"tablib", "enter")
        await settle(app, pilot)
        await pilot.press("j")
        chosen = table.grid.current_key
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen)
        assert app.screen.instance_id == chosen
        await pilot.press("escape")
        await settle(app, pilot)
        assert isinstance(app.screen, TasksScreen)
        assert table.bar.query == "tablib"
        assert table.grid.current_key == chosen


async def test_narrow_terminal_keeps_the_key_columns():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        assert set(table.grid.visible_columns) >= KEY_COLUMNS
        assert "dataset" not in table.grid.visible_columns
        assert all(len(line) <= SMALL[0] for line in screen_text(app).splitlines())


async def test_empty_source_says_why():
    app = GauntletApp(empty_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_tasks(app, pilot)
        assert "No tasks loaded." in screen_text(app)


async def test_failed_load_shows_one_line():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await pilot.press("2")
        await settle(app, pilot)
        text = screen_text(app)
        assert "Couldn't load tasks" in text
        assert "permission denied" in text


async def test_failed_filter_shows_in_place():
    source = make_source()
    app = GauntletApp(source)
    async with app.run_test(size=WIDE) as pilot:
        table = await open_tasks(app, pilot)

        def broken(**_kwargs):
            raise OSError("disk gone")

        source.tasks = broken
        table.query_one(FilterBar).set_facet("repo", "hukkin/tomli")
        await settle(app, pilot)
        text = screen_text(app)
        assert "Couldn't filter the tasks." in text
        assert "disk gone" in text
