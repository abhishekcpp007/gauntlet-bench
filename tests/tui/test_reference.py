from textual.widgets import TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.models import Thresholds
from gauntlet.tui.screens.reference import threshold_rows

from .factories import make_reference, make_source, screen_text

WIDE = (120, 36)


async def open_reference(app: GauntletApp, pilot) -> None:
    await pilot.press("4")
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_reference_tabs_come_from_the_source():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_reference(app, pilot)
        tabs = app.screen.query_one(TabbedContent)
        assert tabs.active == "grading"
        text = screen_text(app)
        assert "Grading 11" in text and "Leak checks 8" in text and "Cheat Catcher 11" in text
        assert "1  Diff" in text and "Hash before and after" in text


async def test_bracket_and_hl_keys_switch_tabs():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_reference(app, pilot)
        tabs = app.screen.query_one(TabbedContent)
        await pilot.press("right_square_bracket")
        assert tabs.active == "leaks"
        await pilot.press("l", "l")
        assert tabs.active == "policies"
        await pilot.press("left_square_bracket")
        assert tabs.active == "rules"
        await pilot.press("h", "h", "h")
        assert tabs.active == "thresholds"
        await pilot.pause()
        text = screen_text(app)
        assert "has to resolve and score at least +0.90" in text
        assert "can't score above -1.00" in text


async def test_every_reference_list_renders():
    reference = make_reference()
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_reference(app, pilot)
        tabs = app.screen.query_one(TabbedContent)
        for pane, items in (
            ("leaks", reference.leak_checks),
            ("rules", reference.rules),
            ("policies", reference.policies),
        ):
            tabs.active = pane
            await pilot.pause()
            text = screen_text(app)
            assert items[0].id in text


def test_threshold_rows_use_the_sources_numbers():
    rows = threshold_rows(Thresholds(oracle_min_reward=0.8, noop_reward=-0.5, cheat_max_reward=0.0))
    assert [r.term for r in rows] == ["oracle", "noop", "cheats"]
    assert "+0.80" in rows[0].what and "-0.50" in rows[1].what and " 0.00" in rows[2].what


async def test_reference_at_80x24():
    app = GauntletApp(make_source())
    async with app.run_test(size=(80, 24)) as pilot:
        await open_reference(app, pilot)
        lines = screen_text(app).splitlines()
        assert all(len(line) <= 80 for line in lines)
        assert "Thresholds" in lines[2]
