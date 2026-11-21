from dataclasses import replace

import pytest
from textual.widgets import Input, OptionList, TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.models import PolicyRow
from gauntlet.tui.screens.episode import EpisodeScreen
from gauntlet.tui.screens.run import (
    ROTTED_NOTE,
    UNCHECKED,
    CalibrationResult,
    RunScreen,
    ordered_policies,
    pass_at_1,
)
from gauntlet.tui.theme import make_look
from gauntlet.tui.widgets import DataGrid, FacetPicker, FilterBar
from gauntlet.tui.widgets.matrix import Matrix

from .factories import GOLDEN, SHIPPED_LIVE, failing_source, screen_text
from .runs_factories import RunsSource, runs_source

WIDE = (140, 40)
SMALL = (80, 24)
TOMLI = "hukkin__tomli-318"


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_run(app: GauntletApp, pilot, run_id: str = GOLDEN) -> RunScreen:
    await settle(app, pilot)
    app.open_run(run_id)
    await settle(app, pilot)
    assert isinstance(app.screen, RunScreen)
    return app.screen


def active_tab(screen: RunScreen) -> str:
    return screen.query_one("#run-tabs", TabbedContent).active


def episodes_grid(screen: RunScreen) -> DataGrid:
    return screen.query_one("#episode-grid", DataGrid)


async def show(app: GauntletApp, pilot, tab: str) -> None:
    app.screen.query_one("#run-tabs", TabbedContent).active = tab
    await settle(app, pilot)


async def pick_facet(app: GauntletApp, pilot, key: str, value: str) -> None:
    await pilot.press("f")
    await pilot.pause()
    assert isinstance(app.screen, FacetPicker)
    options = app.screen.query_one(OptionList)
    options.highlighted = options.get_option_index(f"{key}\0{value}")
    await pilot.press("enter")
    await settle(app, pilot)


async def test_facts_and_trust_numbers():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_run(app, pilot)
        text = screen_text(app)
        assert f"Overview › {GOLDEN}" in text
        for words in (
            "golden before",
            "run folder",
            "/runs/golden/before",
            "12 episodes · 3 tasks · 4 policies",
            "2026-11-12 08:14 to 2026-11-12 09:02",
            "full records",
            "✓ 3/3",
            "oracle resolved",
            "no-op reward",
            "best cheat",
        ):
            assert words in text


async def test_summary_has_one_row_per_policy_in_order():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        assert active_tab(screen) == "summary"
        grid = screen.query_one("#policies", DataGrid)
        assert [r.policy for r in grid.rows] == ["oracle", "noop", "cheater", "cheater:ghost"]
        assert "category" not in grid.visible_columns
        text = screen_text(app)
        assert "1.00 [0.00, 1.00]" in text
        oracle = next(line for line in text.splitlines() if line.startswith("   oracle "))
        assert "+1.00" in oracle
        footer = text.splitlines()[-1]
        for words in ("Open", "Sort", "Copy id", "Filter", "Facets", "Next tab", "Back"):
            assert words in footer


def test_policies_order_by_category_then_kind():
    source = runs_source(split_categories=True)
    detail = source.run(GOLDEN)
    rows = ordered_policies(reversed(detail.policies), detail.summary.policies)
    assert [(r.category, r.policy) for r in rows][:5] == [
        ("swe", "oracle"),
        ("swe", "noop"),
        ("swe", "cheater"),
        ("swe", "cheater:ghost"),
        ("lht", "oracle"),
    ]


async def test_a_run_that_mixes_categories_never_pools_them():
    app = GauntletApp(runs_source(split_categories=True))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        grid = screen.query_one("#policies", DataGrid)
        assert "category" in grid.visible_columns
        assert len(grid.rows) == 2 * len({r.policy for r in grid.rows})
        assert grid.current_key == "oracle (swe)"


async def test_enter_on_a_policy_lists_its_episodes():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        screen.query_one("#policies", DataGrid).focus_table()
        await pilot.press("j", "j", "enter")
        await settle(app, pilot)
        assert active_tab(screen) == "episodes"
        assert screen.query_one("#episodes-filter", FilterBar).facets == {"policy": "cheater"}
        rows = episodes_grid(screen).rows
        assert len(rows) == 3 and {r.policy for r in rows} == {"cheater"}
        assert "policy cheater" in screen_text(app)
        assert "3 of 12" in screen_text(app)


async def test_summary_run_says_what_wasnt_shipped():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot, SHIPPED_LIVE)
        text = screen_text(app)
        assert "◌ summary rows only: the full records weren't shipped" in text
        assert "shipped calibration" in text and "gauntlet-live-2026-11" in text
        oracle = next(line for line in text.splitlines() if line.startswith("   oracle "))
        assert "[" not in oracle
        await show(app, pilot, "calibration")
        assert UNCHECKED.split(". ")[0] in screen_text(app)
        assert not screen.query(CalibrationResult)


async def test_calibration_with_no_violations():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_run(app, pilot)
        await show(app, pilot, "calibration")
        text = screen_text(app)
        assert "The real fix has to resolve and score at least +0.90." in text
        assert "Doing nothing has to score exactly -1.00." in text
        assert "No cheat may resolve or score above 0.00." in text
        assert "✓ No violations" in text
        assert "Rotted" not in text


async def test_calibration_lists_each_violation_and_rotted_task():
    violations = ("oracle didn't resolve hukkin__tomli-318", "cheater:ghost scored +0.40 on [red]x[/red]")
    rotted = (("mahmoud__boltons-471", "base commit gone upstream"),)
    app = GauntletApp(runs_source(violations=violations, rotted=rotted))
    async with app.run_test(size=WIDE) as pilot:
        await open_run(app, pilot)
        await show(app, pilot, "calibration")
        text = screen_text(app)
        assert "▲ 2 violations" in text
        assert f"✗ {violations[0]}" in text
        assert f"✗ {violations[1]}" in text
        assert "No violations" not in text
        assert "Rotted 1 task" in text and ROTTED_NOTE in text
        assert "▲ mahmoud__boltons-471  base commit gone upstream" in text


async def test_matrix_loads_when_its_tab_opens_and_enter_opens_the_episode():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        assert not screen.query(Matrix)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert active_tab(screen) == "matrix"
        matrix = screen.query_one(Matrix)
        assert app.focused is matrix.table
        assert matrix.coordinate == (0, 0)
        text = screen_text(app)
        assert "ghost" in text and "+1.00 ✓" in text and "-1.00 ●" in text
        await pilot.press("l", "l", "enter")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        assert (app.screen.run_id, app.screen.episode_id) == (GOLDEN, f"{TOMLI}__cheater__0")


async def test_episodes_slash_searches_from_any_tab():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        await pilot.press("slash")
        await settle(app, pilot)
        assert active_tab(screen) == "episodes"
        assert isinstance(app.focused, Input)
        await pilot.press(*"boltons")
        await settle(app, pilot)
        rows = episodes_grid(screen).rows
        assert len(rows) == 4 and all("boltons" in r.instance_id for r in rows)
        await pilot.press("escape")
        await settle(app, pilot)
        assert len(episodes_grid(screen).rows) == 12


async def test_episodes_facets_sort_open_and_copy(monkeypatch: pytest.MonkeyPatch):
    app = GauntletApp(runs_source())
    copied: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "copy", lambda text, what="id": copied.append((text, what)))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        await show(app, pilot, "episodes")
        grid = episodes_grid(screen)
        assert app.focused is grid.table
        await pick_facet(app, pilot, "verdict", "cheating")
        assert len(grid.rows) == 3 and {r.cheat_verdict for r in grid.rows} == {"cheating"}
        await pick_facet(app, pilot, "task", TOMLI)
        assert [r.episode_id for r in grid.rows] == [f"{TOMLI}__cheater__0"]
        await pick_facet(app, pilot, "verdict", "")
        await pick_facet(app, pilot, "task", "")
        assert len(grid.rows) == 12
        grid.focus_table()
        await pilot.press("s")
        assert grid.sort is not None and grid.sort.key == "task"
        await pilot.press("s", "s")
        assert grid.sort is not None and grid.sort.key == "reward"
        assert grid.rows and grid.table.get_row_at(0)[2].plain == "+1.00"
        await pilot.press("g", "c")
        first = grid.current_key
        assert copied == [(first, "episode id")]
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        assert app.screen.episode_id == first


async def test_an_errored_episode_shows_the_error_not_its_verdict():
    base = runs_source()
    rows = list(base.episode_rows)
    rows[0] = replace(rows[0], error="sandbox timed out", cheat_verdict="clean")
    app = GauntletApp(runs_source(episode_rows=tuple(rows)))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        await show(app, pilot, "episodes")
        line = next(line for line in screen_text(app).splitlines() if rows[0].instance_id in line)
        assert "! error" in line and "✓ clean" not in line
        assert "sandbox timed out" in line
        assert episodes_grid(screen).rows[0].error == "sandbox timed out"


async def test_a_run_with_no_episodes():
    source = RunsSource(run_ids=("empty",))
    app = GauntletApp(source)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot, "empty")
        text = screen_text(app)
        assert "0 episodes · 0 tasks · 0 policies" in text
        assert "No policies in this run." in text
        await show(app, pilot, "matrix")
        assert "there's no matrix" in screen_text(app)
        await show(app, pilot, "episodes")
        assert "No episodes in this run." in screen_text(app)
        assert isinstance(screen, RunScreen)


async def test_error_state_keeps_the_app_alive():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_run(GOLDEN)
        await settle(app, pilot)
        text = screen_text(app)
        assert "Couldn't load the run" in text and "permission denied" in text
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, RunScreen)


async def test_c_copies_the_run_id():
    app = GauntletApp(runs_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_run(app, pilot)
        assert screen.copy_target() == (GOLDEN, "run id")


async def test_every_tab_fits_80x24():
    app = GauntletApp(runs_source(split_categories=True))
    async with app.run_test(size=WIDE) as pilot:
        await open_run(app, pilot)
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        for tab, words in (
            ("summary", ("Policy", "Resolved", "oracle", "✓ 3/3")),
            ("matrix", ("Task", "oracle", "✓ resolved")),
            ("episodes", ("Task", "Reward", "Verdict")),
            ("calibration", ("No violations",)),
        ):
            await show(app, pilot, tab)
            text = screen_text(app)
            assert all(len(line) <= SMALL[0] for line in text.splitlines()), tab
            for word in words:
                assert word in text, (tab, word)


def test_policy_rows_without_an_interval_show_a_dash():
    row = runs_source().run(SHIPPED_LIVE).policies[0]
    assert isinstance(row, PolicyRow) and row.pass_at_1 is None
    assert pass_at_1(row, make_look({})).plain == "-"
