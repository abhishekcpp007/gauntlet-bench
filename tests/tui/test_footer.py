from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.dataset import DatasetScreen

from .factories import LIVE, make_source, screen_text
from .fakejobs import FakeJobRunner
from .wait import wait_until

NARROW = (80, 24)
WIDE = (180, 40)


async def dataset_footer(size: tuple[int, int]) -> str:
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=size) as pilot:
        app.open_dataset(LIVE)
        await wait_until(pilot, lambda: isinstance(app.screen, DatasetScreen) and not app.screen.loading)
        await pilot.pause()
        return screen_text(app).splitlines()[-1]


async def test_back_help_and_quit_keep_their_place_at_80_columns():
    footer = await dataset_footer(NARROW)
    assert "Back" in footer and "Help" in footer and footer.rstrip().endswith("q Quit")
    assert "Calibrate" not in footer


async def test_the_workbench_keys_show_when_there_is_room():
    footer = await dataset_footer(WIDE)
    assert "Calibrate" in footer and "Leak check" in footer and "Quit" in footer
