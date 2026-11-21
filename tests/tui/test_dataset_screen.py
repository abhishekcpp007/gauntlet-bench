from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.dataset import Bar, Bars, DatasetScreen, funnel
from gauntlet.tui.screens.task import TaskScreen
from gauntlet.tui.screens.tasks import TaskTable

from .factories import LHT, LIVE, WidgetApp, failing_source, make_source, screen_text

WIDE = (140, 40)
SMALL = (80, 24)


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_dataset(app: GauntletApp, pilot, dataset_id: str = LIVE) -> DatasetScreen:
    await settle(app, pilot)
    app.open_dataset(dataset_id)
    await settle(app, pilot)
    assert isinstance(app.screen, DatasetScreen)
    return app.screen


def test_funnel_walks_from_prs_collected_to_tasks_kept():
    detail = make_source().dataset(LIVE)
    bars = funnel(detail)
    assert [b.label for b in bars] == ["PRs collected", "filter", "validate", "leakcheck", "Tasks kept"]
    assert [b.value for b in bars] == [186, 71, 59, 53, 5]
    assert bars[1].ghost == 115 and bars[1].note == "-115"


def test_no_funnel_without_stats():
    assert funnel(make_source().dataset(LHT)) == []


async def test_bars_draw_in_ascii_too():
    app = WidgetApp(Bars([Bar("kept", 3, 3), Bar("dropped", 1, 1, ghost=2, note="-2")]), ascii=True)
    async with app.run_test(size=(60, 5)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "#" in text and "." in text and "█" not in text
        assert "-2" in text


async def test_numbers_funnel_and_repos_show():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot)
        text = screen_text(app)
        for words in (
            "leak checks",
            "✓ 5/5",
            "merged 2026-09-07 to 2026-10-30",
            "Funnel · 186 PRs to 5 tasks",
            "PRs collected",
            "-115",
            "Tasks kept",
            "Tasks by repo · 5",
            "mahmoud/boltons",
        ):
            assert words in text


async def test_a_set_without_stats_says_so():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot, LHT)
        assert "No funnel for this set." in screen_text(app)


async def test_task_table_holds_only_this_set_and_filters_within_it():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_dataset(app, pilot)
        table = screen.query_one(TaskTable)
        assert {r.dataset_id for r in table.grid.rows} == {LIVE}
        await pilot.press("slash", *"boltons")
        await settle(app, pilot)
        assert [r.instance_id for r in table.grid.rows] == ["mahmoud__boltons-471"]
        assert "1 of 5" in screen_text(app)
        await pilot.press("escape")
        table.bar.set_facet("repo", "hukkin/tomli")
        await settle(app, pilot)
        assert [r.instance_id for r in table.grid.rows] == ["hukkin__tomli-318"]


async def test_f_offers_this_sets_facets():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_dataset(app, pilot)
        groups = screen.query_one(TaskTable).bar.groups
        assert [g.key for g in groups] == ["repo", "category", "runner"]
        assert sum(f.count for f in groups[0].facets) == 5


async def test_enter_opens_a_task_and_c_copies_it():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot)
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == "hukkin__tomli-318"
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen)
        assert app.screen.instance_id == "hukkin__tomli-318"


async def test_narrow_terminal_keeps_the_key_columns():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_dataset(app, pilot)
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        assert all(len(line) <= SMALL[0] for line in screen_text(app).splitlines())
        columns = screen.query_one(TaskTable).grid.visible_columns
        assert {"id", "repo", "f2p", "leak"} <= set(columns)


async def test_unknown_dataset_says_so():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot, "nope")
        assert "Nothing called nope was loaded." in screen_text(app)


async def test_failed_load_shows_one_line():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot)
        text = screen_text(app)
        assert "Couldn't load the dataset" in text
        assert "permission denied" in text


async def test_a_set_with_no_tasks_says_so():
    app = GauntletApp(make_source(task_rows=()))
    async with app.run_test(size=WIDE) as pilot:
        await open_dataset(app, pilot)
        assert "This set has no tasks." in screen_text(app)
