from dataclasses import replace

from textual.app import App, ComposeResult
from textual.widgets import Button, Static

from gauntlet.tui.jobtypes import Step
from gauntlet.tui.screens.confirm import ConfirmJob

from .fakejobs import fake_machine, make_spec

SMALL = (80, 24)
LONG_PATH = "/" + "/".join(["a-very-long-folder-name"] * 12)
STEPS = 6


class Host(App[bool]):
    def compose(self) -> ComposeResult:
        yield Static("under")


async def test_start_stays_on_screen_however_long_the_plan_is():
    steps = tuple(
        Step(f"Step {n}", ("calibrate", "--tasks", LONG_PATH, "-o", LONG_PATH)) for n in range(STEPS)
    )
    spec = replace(make_spec(), steps=steps)
    app = Host()
    async with app.run_test(size=SMALL) as pilot:
        app.push_screen(ConfirmJob(spec, fake_machine(), waits=True))
        await pilot.pause()
        start = app.screen.query_one("#start", Button)
        region = start.region
        assert region.height and 0 <= region.y and region.bottom <= SMALL[1]
        assert app.focused is start
        plan = app.screen.query_one(".confirm-plan")
        assert plan.max_scroll_y > 0
