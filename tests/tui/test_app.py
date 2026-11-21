from collections.abc import Iterable
from dataclasses import replace

from textual.command import CommandPalette
from textual.widget import Widget
from textual.widgets import Input, Static, TabbedContent, TabPane

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.models import Facet, TaskRow
from gauntlet.tui.screens.base import DataScreen
from gauntlet.tui.screens.dataset import DatasetScreen
from gauntlet.tui.screens.episode import EpisodeScreen
from gauntlet.tui.screens.help import HelpScreen
from gauntlet.tui.screens.overview import OverviewScreen
from gauntlet.tui.screens.reference import ReferenceScreen
from gauntlet.tui.screens.run import RunScreen
from gauntlet.tui.screens.runs import RunsScreen
from gauntlet.tui.screens.task import TaskScreen
from gauntlet.tui.screens.tasks import TasksScreen
from gauntlet.tui.widgets import Column, DataGrid, FacetGroup, FacetPicker, FilterBar
from gauntlet.tui.widgets.chrome import TopBar

from .factories import GOLDEN, LIVE, TASK_ROWS, empty_source, failing_source, make_source, screen_text

WIDE = (120, 36)
SMALL = (80, 24)


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


def top_line(app: GauntletApp) -> str:
    return screen_text(app).splitlines()[0]


async def test_starts_on_the_overview_with_whats_loaded():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert app.theme == "gauntlet-dark"
        line = top_line(app)
        assert line.startswith(" GAUNTLET  Overview")
        assert line.rstrip().endswith("12 tasks · 2 runs")
        assert isinstance(app.focused, Widget) and app.focused.parent.id == "datasets"


async def test_number_keys_switch_destination_and_keep_each_stack():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        for key, screen in (
            ("2", TasksScreen),
            ("3", RunsScreen),
            ("4", ReferenceScreen),
            ("1", OverviewScreen),
        ):
            await pilot.press(key)
            await settle(app, pilot)
            assert isinstance(app.screen, screen)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen)
        await pilot.press("3")
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        await pilot.press("1")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen)


async def test_enter_on_a_dataset_opens_it_and_esc_comes_back():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen) and app.screen.dataset_id == LIVE
        assert "Overview › gauntlet-live-2026-11" in top_line(app)
        assert "gauntlet-live-2026-11" in screen_text(app)
        await pilot.press("escape")
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert "›" not in top_line(app)


async def test_enter_on_a_run_opens_it_and_backspace_comes_back():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("tab")
        assert app.focused is not None and app.focused.parent.id == "runs"
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen) and app.screen.run_id == GOLDEN
        await pilot.press("backspace")
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert app.focused is not None and app.focused.parent.id == "runs"


async def test_esc_on_a_root_screen_does_nothing_and_hides_from_the_footer():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert "Back" not in screen_text(app).splitlines()[-1]
        await pilot.press("escape")
        assert isinstance(app.screen, OverviewScreen)


async def test_open_methods_push_each_detail_screen():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_task("hukkin__tomli-318")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen)
        app.open_run(GOLDEN)
        await settle(app, pilot)
        app.open_episode(GOLDEN, "hukkin__tomli-318__cheater__0")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        text = screen_text(app)
        assert "-1.00" in text and "● cheating" in text
        assert "Overview › hukkin__tomli-318 › golden › hukkin__tomli-318__cheater__0" in text.splitlines()[0]


async def test_help_lists_the_real_bindings():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        text = screen_text(app)
        for words in ("Sort", "Copy id", "Open", "Help", "Quit", "Overview", "Reference", "Everywhere"):
            assert words in text
        groups = [name for name, _ in app.screen.groups]
        assert groups[-1] == "Everywhere"
        await pilot.press("escape")
        assert isinstance(app.screen, OverviewScreen)


async def test_palette_jumps_to_a_task_by_id():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+p")
        await pilot.pause()
        assert isinstance(app.screen, CommandPalette)
        await pilot.press(*"pluggy-759")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen) and app.screen.instance_id == "pytest-dev__pluggy-759"


async def test_palette_jumps_to_an_episode():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("ctrl+p")
        await pilot.press(*"boltons-471__cheater__0")
        await pilot.pause(0.5)
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        assert app.screen.run_id == GOLDEN


async def test_c_copies_the_row_id_with_a_toast():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == LIVE
        assert any(LIVE in str(n.message) for n in app._notifications)
        app.open_task("hukkin__tomli-318")
        await settle(app, pilot)
        app.screen.set_focus(None)
        await pilot.press("c")
        assert app.clipboard == "hukkin__tomli-318"


async def test_empty_source_says_what_to_do():
    app = GauntletApp(empty_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        text = screen_text(app)
        assert "No datasets loaded." in text and "--datasets DIR" in text
        assert "No runs loaded." in text and "--run DIR" in text
        assert "0 tasks · 0 runs" in text


async def test_failing_source_shows_errors_and_stays_alive():
    app = GauntletApp(failing_source("can't read results.jsonl: permission denied"))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        text = screen_text(app)
        assert "Couldn't load the overview" in text
        assert "LoadFailed: can't read results.jsonl: permission denied" in text
        await pilot.press("4")
        await settle(app, pilot)
        assert "Couldn't load the reference" in screen_text(app)
        app.open_task("nope")
        await settle(app, pilot)
        assert "Couldn't load the task" in screen_text(app)
        assert app.is_running


async def test_missing_id_is_a_plain_message():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_run("no-such-run")
        await settle(app, pilot)
        assert "Nothing called no-such-run was loaded." in screen_text(app)


async def test_every_destination_fits_80x24():
    app = GauntletApp(make_source())
    async with app.run_test(size=SMALL) as pilot:
        for key in ("1", "2", "3", "4"):
            await pilot.press(key)
            await settle(app, pilot)
            lines = screen_text(app).splitlines()
            assert len(lines) == SMALL[1]
            assert all(len(line) <= SMALL[0] for line in lines)
        await pilot.press("question_mark")
        await pilot.pause()
        assert "Everywhere" in screen_text(app)


async def test_resize_reflows_the_overview():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        grid = app.screen.query_one("#datasets", DataGrid)
        wide = grid.visible_columns
        await pilot.resize_terminal(*SMALL)
        await pilot.pause()
        assert len(grid.visible_columns) < len(wide)
        await pilot.resize_terminal(*WIDE)
        await pilot.pause()
        assert grid.visible_columns == wide


async def test_ascii_mode_draws_only_ascii():
    app = GauntletApp(make_source(), ascii=True)
    async with app.run_test(size=WIDE) as pilot:
        for key in ("1", "4"):
            await pilot.press(key)
            await settle(app, pilot)
            text = screen_text(app)
            assert text.isascii(), [ch for ch in text if not ch.isascii()][:5]
        await pilot.press("1")
        await settle(app, pilot)
        assert "+ 96/96" in screen_text(app)


async def test_no_color_keeps_every_status_readable(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert app.no_color
        text = screen_text(app)
        assert "✓ none" in text and "◌ summary" in text and "-1.00" in text


async def test_light_theme_and_switching():
    app = GauntletApp(make_source(), theme="gauntlet-light")
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert app.theme == "gauntlet-light"
        assert {"gauntlet-dark", "gauntlet-light"} <= set(app.available_themes)
        app.theme = "gauntlet-dark"
        await pilot.pause()
        assert "gauntlet-live-2026-11" in screen_text(app)


async def test_untrusted_task_text_shows_literally():
    row = replace(TASK_ROWS[0], instance_id="evil-1", pr_title="[red]boom[/red] \x1b[31mx")
    app = GauntletApp(make_source(task_rows=(row,)))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_task("evil-1")
        await settle(app, pilot)
        text = screen_text(app)
        assert "[red]boom[/red] ^[[31mx" in text


class FilteredTasks(DataScreen[tuple[TaskRow, ...]]):
    crumb = "Filtered"
    what = "tasks"

    def fetch(self) -> tuple[TaskRow, ...]:
        return self.source.tasks()

    def build(self, data: tuple[TaskRow, ...]) -> Iterable[Widget]:
        self.bar = FilterBar([FacetGroup("runner", "Runner", (Facet("pytest", 8), Facet("vitest", 3)))])
        self.grid: DataGrid[TaskRow] = DataGrid(
            [Column("id", "Instance", lambda t: t.instance_id, kind="id")], key=lambda t: t.instance_id
        )
        self.grid.set_rows(data)
        yield self.bar
        yield self.grid

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        rows = self.source.tasks(query=event.query, runner=event.facets.get("runner"))
        self.grid.set_rows(rows)


async def test_slash_and_f_drive_a_screens_filter_bar():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        screen = FilteredTasks()
        await app.push_screen(screen)
        await settle(app, pilot)
        await pilot.press("slash")
        assert isinstance(app.focused, Input)
        await pilot.press(*"tomli", "1")
        await pilot.pause()
        assert isinstance(app.screen, FilteredTasks)
        assert screen.bar.query == "tomli1"
        await pilot.press("backspace")
        await pilot.pause()
        assert [r.instance_id for r in screen.grid.rows] == ["hukkin__tomli-318"]
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, FilteredTasks) and screen.bar.query == ""
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FacetPicker)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, FilteredTasks)
        assert "Next tab" not in screen_text(app).splitlines()[-1]


async def test_breadcrumbs_cut_long_ids_in_the_middle():
    app = GauntletApp(make_source())
    async with app.run_test(size=SMALL) as pilot:
        await settle(app, pilot)
        app.open_episode(GOLDEN, "jazzband__tablib-v3.8.0_to_v3.9.0__cheater:ghost__0")
        await settle(app, pilot)
        line = app.screen.query_one(TopBar)
        text = top_line(app)
        assert len(text) <= SMALL[0] and "…" in text and text.rstrip().endswith("2 runs")
        assert line.crumbs[-1].startswith("jazzband")


async def test_narrow_footer_drops_the_palette_hint_but_keeps_quit():
    app = GauntletApp(make_source())
    async with app.run_test(size=SMALL) as pilot:
        await settle(app, pilot)
        footer = screen_text(app).splitlines()[-1]
        assert "Quit" in footer and "Palette" not in footer
        await pilot.resize_terminal(*WIDE)
        await settle(app, pilot)
        assert "Palette" in screen_text(app).splitlines()[-1]


class TabbedFilter(DataScreen[tuple[TaskRow, ...]]):
    crumb = "Tabbed"
    what = "tasks"

    def fetch(self) -> tuple[TaskRow, ...]:
        return self.source.tasks()

    def build(self, data: tuple[TaskRow, ...]) -> Iterable[Widget]:
        tabs = TabbedContent()
        tabs.compose_add_child(TabPane("Plain", Static("nothing to filter"), id="plain"))
        bar = FilterBar([FacetGroup("runner", "Runner", (Facet("pytest", 8),))])
        tabs.compose_add_child(TabPane("List", bar, id="list"))
        yield tabs


async def test_filter_keys_only_see_the_visible_tab():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        screen = TabbedFilter()
        await app.push_screen(screen)
        await settle(app, pilot)
        assert not screen.check_action("filter", ())
        assert not screen.check_action("facets", ())
        assert "Filter" not in screen_text(app).splitlines()[-1]
        await pilot.press("slash")
        assert not isinstance(app.focused, Input)
        await pilot.press("right_square_bracket")
        await pilot.pause()
        assert screen.check_action("filter", ()) and screen.check_action("facets", ())
        assert "Filter" in screen_text(app).splitlines()[-1]
        await pilot.press("slash")
        assert isinstance(app.focused, Input)
