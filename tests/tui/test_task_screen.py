from dataclasses import replace

from textual.widgets import TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.episode import EpisodeScreen
from gauntlet.tui.screens.task import IdList, PassToPass, TaskScreen, TestGrid
from gauntlet.tui.widgets import Checklist, DataGrid, DiffView

from .factories import (
    GOLDEN,
    HOSTILE_PATCH,
    TASK_ROWS,
    FakeSource,
    failing_source,
    make_episode_row,
    make_source,
    make_task_detail,
    screen_text,
)

WIDE = (140, 40)
SMALL = (80, 24)
TOMLI = "hukkin__tomli-318"
TABLIB = "jazzband__tablib-v3.8.0_to_v3.9.0"
EXSOLVE = "unjs__exsolve-80"
SWE_TABS = ["statement", "tests", "leaks", "patches", "episodes"]


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_task(app: GauntletApp, pilot, instance_id: str = TOMLI) -> TaskScreen:
    await settle(app, pilot)
    app.open_task(instance_id)
    await settle(app, pilot)
    assert isinstance(app.screen, TaskScreen)
    return app.screen


async def show_tab(app: GauntletApp, pilot, tab: str) -> None:
    app.screen.query_one(TabbedContent).active = tab
    await settle(app, pilot)


def tab_ids(screen: TaskScreen) -> list[str]:
    return [pane.id for pane in screen.query("TabPane") if pane.id]


def source_with(detail) -> FakeSource:
    source = make_source()
    source.task_details[detail.row.instance_id] = detail
    return source


async def test_facts_show_the_task():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot)
        text = screen_text(app)
        for words in (
            "hukkin/tomli",
            "#318 Fix a crash on a comment at the end of the file",
            "https://github.com/hukkin/tomli/pull/318",
            "2026-10-06 11:01",
            "swe · pytest · python",
            "the linked GitHub issue",
            "8b04a9c8ff22041c5c02e1d7a3b4c5d6",
            "1da01ef8c2d3",
        ):
            assert words in text


async def test_swe_task_has_no_horizon_tab():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        assert tab_ids(screen) == SWE_TABS


async def test_lht_task_shows_its_release_range():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot, TABLIB)
        assert tab_ids(screen) == [*SWE_TABS, "horizon"]
        await show_tab(app, pilot, "horizon")
        text = screen_text(app)
        assert "v3.8.0 to v3.9.0" in text
        assert "1,840 lines added or removed" in text
        assert "#100" in text and "Change 1 in the range" in text
        assert "4f1c2ab" in text
        assert "Milestone 1 · 3 tests" in text
        lists = {widget.title: widget.ids for widget in screen.query(IdList)}
        assert lists["Dropped regressions"] == ()


async def test_bracket_keys_switch_tabs():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        tabs = screen.query_one(TabbedContent)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert tabs.active == "tests"
        await pilot.press("left_square_bracket", "left_square_bracket")
        await settle(app, pilot)
        assert tabs.active == "episodes"


async def test_statement_shows_untrusted_text_literally():
    detail = make_task_detail(problem_statement="[red]boom[/red] \x1b[31mred\x1b[0m")
    app = GauntletApp(source_with(detail))
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot)
        text = screen_text(app)
        assert "[red]boom[/red]" in text
        assert "^[[31mred^[[0m" in text
        assert "taken from the linked GitHub issue" in text


async def test_tests_tab_explains_each_class_and_the_validation_runs():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot)
        await show_tab(app, pilot, "tests")
        text = screen_text(app)
        for words in (
            "F2P  fail to pass",
            "tests the fix makes pass",
            "tests that didn't exist before",
            "tests that passed before and must keep",
            "only part of the suite runs: tests",
            "scope full, 3 m 04 s in all",
            "Base run",
            "Fix run 2",
        ):
            assert words in text
        lists = {widget.title: widget.ids for widget in app.screen.query(IdList)}
        assert lists["Fail to pass"] == ("tests/test_misc.py::TestMiscellaneous::test_case_0",)
        assert lists["Test files"] == ("tests/test_misc.py",)


async def test_p2p_list_loads_only_when_the_tab_opens():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        assert not screen.query(PassToPass)
        await show_tab(app, pilot, "tests")
        grid = screen.query_one(TestGrid)
        assert len(grid.rows) == TASK_ROWS[0].p2p
        assert "Pass to pass · 312" in screen_text(app)


async def test_slash_searches_the_p2p_list_on_the_tests_tab_only():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        assert not screen.check_action("filter", ())
        await show_tab(app, pilot, "tests")
        assert screen.check_action("filter", ())
        await pilot.press("slash", *"test_30")
        await settle(app, pilot)
        rows = screen.query_one(TestGrid).rows
        assert rows and all("test_30" in t for t in rows)
        assert f"{len(rows)} of 312" in screen_text(app)


async def test_enter_on_a_test_id_does_nothing():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        await show_tab(app, pilot, "tests")
        screen.query_one(TestGrid).focus_table()
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is screen
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "tests/test_api.py::test_0"


async def test_leak_check_lists_all_eight():
    row = replace(TASK_ROWS[0], leakcheck_ok=False)
    app = GauntletApp(source_with(make_task_detail(row)))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        await show_tab(app, pilot, "leaks")
        checklist = screen.query_one(Checklist)
        assert len(checklist.items) == 8
        assert checklist.passing == 7
        text = screen_text(app)
        assert "Leak check 7/8" in text
        assert "whether the agent's sandbox can see the answer" in text
        assert "✗" in text and "failed" in text
        assert "1 gold line(s) readable" in text


async def test_patches_load_lazily_and_show_untrusted_text_literally():
    detail = make_task_detail(gold_patch=HOSTILE_PATCH, test_patch_truncated=True)
    app = GauntletApp(source_with(detail))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        assert not screen.query(DiffView)
        await show_tab(app, pilot, "patches")
        assert len(screen.query(DiffView)) == 2
        text = screen_text(app)
        assert "An agent never sees either of these." in text
        assert "[bold red]boom[/bold red]" in text
        assert "Merged fix · 1 file" in text
        assert "cut short" in screen.query_one("#test-pane").border_subtitle
        assert not screen.query_one("#gold-pane").border_subtitle


async def test_episodes_tab_opens_an_episode():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        await show_tab(app, pilot, "episodes")
        grid = screen.query_one("#episodes-grid", DataGrid)
        assert len(grid.rows) == 7
        assert "cheater:ghost" in screen_text(app)
        grid.focus_table()
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        assert (app.screen.run_id, app.screen.episode_id) == (GOLDEN, f"{TOMLI}__oracle__0")


async def test_an_errored_episode_shows_the_error_not_its_verdict():
    errored = make_episode_row(policy="cheater", cheat_verdict="clean", error="sandbox died")
    app = GauntletApp(source_with(make_task_detail(episodes=(errored,))))
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot)
        await show_tab(app, pilot, "episodes")
        text = screen_text(app)
        assert "! error" in text
        assert "✓ clean" not in text


async def test_episodes_tab_says_when_no_run_has_the_task():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot, EXSOLVE)
        await show_tab(app, pilot, "episodes")
        assert "No loaded run includes this task." in screen_text(app)


async def test_c_copies_the_focused_fact():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        screen.query_one("#facts-env").focus()
        await pilot.press("j", "j", "c")
        await pilot.pause()
        assert app.clipboard == "8b04a9c8ff22041c5c02e1d7a3b4c5d6"
        assert screen.copy_target() == (TOMLI, "instance id")


async def test_narrow_terminal_keeps_facts_and_tabs_readable():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        await show_tab(app, pilot, "episodes")
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        text = screen_text(app)
        assert all(len(line) <= SMALL[0] for line in text.splitlines())
        assert "hukkin/tomli" in text and "Statement" in text
        columns = screen.query_one("#episodes-grid", DataGrid).visible_columns
        assert {"run", "policy", "reward", "verdict"} <= set(columns)


async def test_unknown_task_says_so():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot, "nope__nope-1")
        assert "Nothing called nope__nope-1 was loaded." in screen_text(app)


async def test_failed_load_shows_one_line():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_task(app, pilot)
        text = screen_text(app)
        assert "Couldn't load the task" in text
        assert "permission denied" in text


async def test_short_terminal_folds_the_facts_into_one_line():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_task(app, pilot)
        assert screen.query_one("#task-facts").display
        assert not screen.query_one("#task-line").display
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        assert not screen.query_one("#task-facts").display
        assert screen.query_one("#task-line").display
        assert "hukkin/tomli · #318 · 2026-10-06 · swe · pytest" in screen_text(app)
