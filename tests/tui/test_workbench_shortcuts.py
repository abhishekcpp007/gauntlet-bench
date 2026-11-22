"""Every Workbench key on every viewer screen opens the REAL form with the value filled in, over
the real store."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from textual.widgets import SelectionList

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.base import DataScreen
from gauntlet.tui.screens.workbench import WorkbenchScreen
from gauntlet.tui.widgets.grid import DataGrid
from gauntlet.tui.widgets.pickers import Picker

from .factories import screen_text
from .fakejobs import FakeJobRunner
from .sample import LIVE_ID, RUN_ID, TOMLI, TOMLI_CHEATER, sample_store
from .wait import wait_until

SIZE = (180, 50)
HIGHLIGHTED = "the run highlighted in the list"
Open = Callable[[GauntletApp], None] | str
"""How to reach the viewer screen: an `open_*` call, or a destination key."""


def picked(screen: WorkbenchScreen, action: str, field: str) -> object:
    control = screen.forms[action].row(field).control
    if isinstance(control, Picker):
        return control.value
    if isinstance(control, SelectionList):
        return tuple(control.selected)
    return getattr(control, "value", None)


CASES: list[tuple[str, Open, str, str, dict[str, object]]] = [
    ("task P", lambda app: app.open_task(TOMLI), "P", "try_patch", {"tasks": LIVE_ID, "task": TOMLI}),
    ("task L", lambda app: app.open_task(TOMLI), "L", "leakcheck", {"tasks": LIVE_ID}),
    ("dataset C", lambda app: app.open_dataset(LIVE_ID), "C", "calibrate", {"tasks": LIVE_ID}),
    ("dataset O", lambda app: app.open_dataset(LIVE_ID), "O", "run_policies", {"tasks": LIVE_ID}),
    ("dataset L", lambda app: app.open_dataset(LIVE_ID), "L", "leakcheck", {"tasks": LIVE_ID}),
    ("dataset E", lambda app: app.open_dataset(LIVE_ID), "E", "check_envs", {"tasks": (LIVE_ID,)}),
    ("tasks M", "2", "M", "make_tasks", {}),
    ("run R", lambda app: app.open_run(RUN_ID), "R", "report", {"run": RUN_ID}),
    ("runs R", "3", "R", "report", {"run": HIGHLIGHTED}),
    (
        "episode P",
        lambda app: app.open_episode(RUN_ID, TOMLI_CHEATER),
        "P",
        "try_patch",
        {"tasks": LIVE_ID, "task": TOMLI},
    ),
]


@pytest.mark.parametrize(
    ("case", "open_screen", "key", "action", "expected"), CASES, ids=[c[0] for c in CASES]
)
async def test_each_key_opens_the_real_form_filled_in(case, open_screen, key, action, expected):
    app = GauntletApp(sample_store(), jobs=FakeJobRunner())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        if isinstance(open_screen, str):
            await pilot.press(open_screen)
        else:
            open_screen(app)
        await wait_until(
            pilot,
            lambda: isinstance(app.screen, DataScreen) and not app.screen.loading and app.screen.is_mounted,
            what="the viewer screen",
        )
        await app.workers.wait_for_complete()
        await pilot.pause()
        if HIGHLIGHTED in expected.values():
            current = app.screen.query_one("#runs", DataGrid).current_key
            expected = {
                field: current if value == HIGHLIGHTED else value for field, value in expected.items()
            }
        await pilot.press(key)
        await wait_until(
            pilot,
            lambda: isinstance(app.screen, WorkbenchScreen) and app.screen.current == action,
            what=f"the {action} form",
        )
        screen = app.screen
        assert isinstance(screen, WorkbenchScreen)
        await wait_until(
            pilot,
            lambda: all(picked(screen, action, f) == v for f, v in expected.items()),
            what=f"{expected} in the {action} form",
        )
        assert "Couldn't" not in screen_text(app)
