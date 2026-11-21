import pytest

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.run import RunScreen
from gauntlet.tui.screens.runs import INTRO, RunsScreen, matches
from gauntlet.tui.widgets import DataGrid

from .factories import GOLDEN, SHIPPED_LIVE, empty_source, failing_source, make_source, screen_text

WIDE = (140, 36)
SMALL = (80, 24)


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_runs(app: GauntletApp, pilot) -> DataGrid:
    await settle(app, pilot)
    await pilot.press("3")
    await settle(app, pilot)
    assert isinstance(app.screen, RunsScreen)
    return app.screen.query_one("#runs", DataGrid)


def capture_copies(app: GauntletApp, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    copied: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "copy", lambda text, what="id": copied.append((text, what)))
    return copied


async def test_lists_every_run_with_its_trust_numbers():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        grid = await open_runs(app, pilot)
        assert [r.id for r in grid.rows] == [GOLDEN, SHIPPED_LIVE]
        text = screen_text(app)
        assert INTRO in text
        assert "Runs · 2" in text
        headers = ("Run", "Kind", "Detail", "Episodes", "Oracle", "No-op", "Best cheat", "Violations", "Ran")
        assert all(header in text for header in headers)
        golden = next(line for line in text.splitlines() if f" {GOLDEN} " in line)
        assert "folder" in golden and "full" in golden and "✓ 3/3" in golden and "✓ none" in golden
        assert "2026-11-12" in golden
        shipped = next(line for line in text.splitlines() if SHIPPED_LIVE in line)
        assert "shipped" in shipped and "◌ summary" in shipped
        assert "-1.00" in shipped


async def test_footer_keys():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_runs(app, pilot)
        footer = screen_text(app).splitlines()[-1]
        for words in ("Open", "Sort", "Copy", "Filter", "Help", "Quit"):
            assert words in footer
        assert "Facets" not in footer


async def test_enter_opens_the_run():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_runs(app, pilot)
        await pilot.press("j", "enter")
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen)
        assert app.screen.run_id == SHIPPED_LIVE
        await pilot.press("escape")
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        assert app.screen.query_one("#runs", DataGrid).current_key == SHIPPED_LIVE


async def test_slash_filters_and_esc_clears():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        grid = await open_runs(app, pilot)
        await pilot.press("slash", *"shipped")
        await pilot.pause()
        assert [r.id for r in grid.rows] == [SHIPPED_LIVE]
        assert "1 of 2" in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        assert len(grid.rows) == 2
        await pilot.press("slash", *"nothing like this")
        await pilot.pause()
        assert "No runs match." in screen_text(app)


def test_matches_looks_at_id_title_kind_and_dataset():
    run = make_source().runs()[1]
    assert matches(run, "")
    assert matches(run, "LIVE calibration")
    assert matches(run, "gauntlet-live-2026")
    assert not matches(run, "folder")


async def test_s_sorts_and_c_copies_the_run_id(monkeypatch: pytest.MonkeyPatch):
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        grid = await open_runs(app, pilot)
        copied = capture_copies(app, monkeypatch)
        await pilot.press("s")
        assert grid.sort is not None and grid.sort.key == "id"
        await pilot.press("S")
        assert grid.table.get_row_at(0)[0].plain == SHIPPED_LIVE
        await pilot.press("g", "c")
        assert copied == [(SHIPPED_LIVE, "run id")]


async def test_empty_state_says_how_to_load_a_run():
    app = GauntletApp(empty_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_runs(app, pilot)
        text = screen_text(app)
        assert "No runs loaded." in text
        assert "gauntlet tui --run <folder>" in text


async def test_error_state_keeps_the_app_alive():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("3")
        await settle(app, pilot)
        text = screen_text(app)
        assert "Couldn't load runs" in text
        assert "permission denied" in text


async def test_fits_80x24():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_runs(app, pilot)
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        text = screen_text(app)
        assert all(len(line) <= SMALL[0] for line in text.splitlines())
        assert INTRO in text
        for words in ("Run", "Episodes", "Oracle", "Best cheat", "Violations", GOLDEN, "shipped:"):
            assert words in text
        assert "…" in text
