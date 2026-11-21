"""--ascii and NO_COLOR over every screen the screen agents built, on the real store."""

from textual.widgets import TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.help import HelpScreen
from gauntlet.tui.widgets.matrix import MatrixTable
from gauntlet.tui.widgets.timeline import StepList

from .factories import screen_text
from .sample import LIVE_ID, PLUGGY, PLUGGY_CHEATER, RUN_ID, TOMLI, TOMLI_CHEATER, sample_store

SIZE = (140, 40)
AGENT_TEXT_TABS = {None, "statement"}


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def every_tab(app: GauntletApp, pilot):
    """Yield (tab id, screen text) for the screen as loaded and then for each of its tabs."""
    await settle(app, pilot)
    yield None, screen_text(app)
    for tabs in list(app.screen.query(TabbedContent)):
        for pane in list(tabs.query("TabPane")):
            tabs.active = pane.id
            await settle(app, pilot)
            yield pane.id, screen_text(app)


def openers(app: GauntletApp):
    return (
        (app.open_dataset, (LIVE_ID,)),
        (app.open_task, (TOMLI,)),
        (app.open_task, (PLUGGY,)),
        (app.open_run, (RUN_ID,)),
        (app.open_episode, (RUN_ID, TOMLI_CHEATER)),
        (app.open_episode, (RUN_ID, PLUGGY_CHEATER)),
    )


async def test_ascii_draws_only_ascii_outside_agent_text():
    app = GauntletApp(sample_store(), ascii=True)
    async with app.run_test(size=SIZE) as pilot:
        for key in ("1", "2", "3", "4"):
            await pilot.press(key)
            async for tab, text in every_tab(app, pilot):
                assert text.isascii(), (key, tab, sorted({c for c in text if not c.isascii()}))
        await pilot.press("1")
        for opener, args in openers(app):
            opener(*args)
            async for tab, text in every_tab(app, pilot):
                if tab not in AGENT_TEXT_TABS:
                    assert text.isascii(), (args, tab, sorted({c for c in text if not c.isascii()}))
            await pilot.press("escape")
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert screen_text(app).isascii()


async def test_no_color_keeps_symbol_and_word_on_the_new_screens(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = GauntletApp(sample_store())
    async with app.run_test(size=SIZE) as pilot:
        assert app.no_color
        app.open_run(RUN_ID)
        await settle(app, pilot)
        app.screen.query_one(TabbedContent).active = "matrix"
        await settle(app, pilot)
        text = screen_text(app)
        assert "✓ resolved" in text and "● cheating" in text and "✗ tampered" in text
        await pilot.press("escape")
        app.open_episode(RUN_ID, TOMLI_CHEATER)
        await settle(app, pilot)
        text = screen_text(app)
        assert "● cheating" in text and "-1.00" in text
        tabs = app.screen.query_one(TabbedContent)
        tabs.active = "evidence"
        await settle(app, pilot)
        assert "● high" in screen_text(app)


async def test_help_names_the_matrix_and_timeline_keys():
    app = GauntletApp(sample_store())
    async with app.run_test(size=SIZE) as pilot:
        app.open_run(RUN_ID)
        await settle(app, pilot)
        app.screen.query_one(TabbedContent).active = "matrix"
        await settle(app, pilot)
        app.screen.query_one(MatrixTable).focus()
        await pilot.press("question_mark")
        await settle(app, pilot)
        assert isinstance(app.screen, HelpScreen)
        groups = [name for name, _ in app.screen.groups]
        assert "Matrix" in groups
        await pilot.press("escape")
        await pilot.press("escape")
        app.open_episode(RUN_ID, TOMLI_CHEATER)
        await settle(app, pilot)
        app.screen.query_one(TabbedContent).active = "trajectory"
        await settle(app, pilot)
        app.screen.query_one(StepList).focus()
        await pilot.press("question_mark")
        await settle(app, pilot)
        groups = [name for name, _ in app.screen.groups]
        assert "Trajectory" in groups


def test_textual_widgets_get_plain_group_names():
    from textual.containers import VerticalScroll
    from textual.widgets import Input, Tabs

    from gauntlet.tui.screens.help import group_name

    assert group_name(Tabs()) == "Tabs"
    assert group_name(Input()) == "Text box"
    assert group_name(VerticalScroll()) == "Scrolling"
