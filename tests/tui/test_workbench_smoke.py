"""The Workbench on the REAL store: every one of the nine actions shows its form, with no error
state, at both sizes."""

from __future__ import annotations

import pytest

from gauntlet.tui.actions import ACTIONS
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.workbench import ActionList, NoForm, WorkbenchScreen
from gauntlet.tui.widgets.form import FieldRow, FormView
from gauntlet.tui.widgets.states import ErrorState

from .factories import screen_text
from .fakejobs import FakeJobRunner
from .sample import sample_store
from .wait import settle, wait_until

SIZES = [(140, 40), (80, 24)]


@pytest.mark.parametrize("size", SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
async def test_every_action_shows_its_form_on_the_real_store(size: tuple[int, int]):
    app = GauntletApp(sample_store(), jobs=FakeJobRunner())
    async with app.run_test(size=size) as pilot:
        await settle(app, pilot)
        await pilot.press("5")
        await wait_until(pilot, lambda: isinstance(app.screen, WorkbenchScreen), what="the Workbench")
        await settle(app, pilot)
        screen = app.screen
        assert isinstance(screen, WorkbenchScreen)
        assert not screen.query(NoForm)
        actions = screen.query_one(ActionList)
        for info in ACTIONS:
            actions.highlighted = actions.get_option_index(info.id)
            await settle(app, pilot)
            view = screen.forms[info.id]
            assert view.display and screen.query_one("#form-pane").border_title == info.title
            rows = list(view.query(FieldRow))
            assert rows and all(row.note.error is None for row in rows), info.id
            assert not screen.query(ErrorState), info.id
            assert view.banner.error is None, info.id
            text = screen_text(app)
            assert "Couldn't" not in text and "Traceback" not in text, info.id
            assert rows[0].field.label in text, info.id
        assert isinstance(screen.query_one(f"#{ACTIONS[-1].id}"), FormView)
