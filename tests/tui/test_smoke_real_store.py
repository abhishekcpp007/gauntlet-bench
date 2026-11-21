"""End to end on the real `Store` over the fixture data: every destination, every kind of detail
screen and every tab, with no error state and no exception. This is what catches a screen that
expects something the real store doesn't give it."""

import pytest
from textual.widgets import TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.widgets import ErrorState

from .factories import screen_text
from .sample import (
    LHT_ID,
    LIVE_ID,
    PLUGGY,
    RUN_ID,
    SHIPPED_LHT,
    SHIPPED_LIVE,
    TOMLI,
    TOMLI_CHEATER,
    sample_store,
)

SIZES = [(140, 40), (80, 24)]


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def visit_every_tab(app: GauntletApp, pilot) -> int:
    """Activate each tab of each tab set on the current screen. Returns how many it visited."""
    await settle(app, pilot)
    done: set[tuple[str | None, str]] = set()
    while True:
        todo = [
            (tabs, pane.id)
            for tabs in app.screen.query(TabbedContent)
            for pane in tabs.query("TabPane")
            if pane.id and (tabs.id, pane.id) not in done and pane.parent.parent is tabs
        ]
        if not todo:
            return len(done)
        tabs, pane_id = todo[0]
        done.add((tabs.id, pane_id))
        tabs.active = pane_id
        await settle(app, pilot)
        errors = app.screen.query(ErrorState)
        assert not errors, f"{type(app.screen).__name__} tab {pane_id}: {screen_text(app)}"


async def check(app: GauntletApp, pilot, what: str, *, tabs: bool = True) -> None:
    visited = await visit_every_tab(app, pilot)
    errors = app.screen.query(ErrorState)
    assert not errors, f"{what}: {[e.message for e in errors]}"
    assert visited or not tabs, f"{what}: no tabs found"


@pytest.mark.parametrize("size", SIZES)
async def test_every_screen_and_tab_on_the_real_store(size):
    app = GauntletApp(sample_store())
    async with app.run_test(size=size) as pilot:
        for key in ("1", "2", "3", "4"):
            await pilot.press(key)
            await check(app, pilot, f"destination {key}", tabs=key == "4")
        await pilot.press("1")
        for opener, args in (
            (app.open_dataset, (LIVE_ID,)),
            (app.open_dataset, (LHT_ID,)),
            (app.open_task, (TOMLI,)),
            (app.open_task, (PLUGGY,)),
            (app.open_run, (RUN_ID,)),
            (app.open_run, (SHIPPED_LIVE,)),
            (app.open_run, (SHIPPED_LHT,)),
            (app.open_episode, (RUN_ID, TOMLI_CHEATER)),
            (app.open_episode, (SHIPPED_LIVE, TOMLI_CHEATER)),
        ):
            opener(*args)
            await check(app, pilot, f"{opener.__name__}{args}", tabs=opener != app.open_dataset)
            await pilot.press("escape")
            await settle(app, pilot)
        assert app.is_running


async def test_every_episode_of_the_sample_run_opens_cleanly():
    store = sample_store()
    app = GauntletApp(store)
    async with app.run_test(size=SIZES[0]) as pilot:
        for row in store.episodes(RUN_ID):
            app.open_episode(RUN_ID, row.episode_id)
            await check(app, pilot, row.episode_id)
            await pilot.press("escape")
            await settle(app, pilot)
