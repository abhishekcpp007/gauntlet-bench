import time
from dataclasses import replace

from textual.widgets import Collapsible, TabbedContent

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.episode import NOTHING_FOUND, EpisodeScreen
from gauntlet.tui.screens.task import TaskScreen
from gauntlet.tui.widgets.diff import DiffView
from gauntlet.tui.widgets.filterbar import FacetPicker, FilterBar
from gauntlet.tui.widgets.grid import DataGrid
from gauntlet.tui.widgets.rewardbar import RewardBar
from gauntlet.tui.widgets.timeline import StepList

from .episode_factories import (
    MANY_TESTS,
    crashed_detail,
    detail,
    lht_detail,
    many_tests,
    odd_trajectory,
    source_with,
)
from .factories import GOLDEN, HOSTILE_PATCH, SHIPPED_LIVE, failing_source, make_source, screen_text

WIDE = (120, 36)
SMALL = (80, 24)
TALL = (120, 60)
ORACLE = "hukkin__tomli-318__oracle__0"
NOOP = "hukkin__tomli-318__noop__0"
CHEATER = "hukkin__tomli-318__cheater__0"
TAMPERED = "mahmoud__boltons-471__cheater__0"
GHOST = "hukkin__tomli-318__cheater:ghost__0"
SUMMARY = "hukkin__tomli-318__oracle__0"
QUICK_SECONDS = 3.0


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def open_episode(app: GauntletApp, pilot, episode_id: str, run_id: str = GOLDEN) -> EpisodeScreen:
    await settle(app, pilot)
    app.open_episode(run_id, episode_id)
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, EpisodeScreen)
    return screen


async def show_tab(app: GauntletApp, pilot, tab: str) -> None:
    app.screen.query_one(TabbedContent).active = tab
    await settle(app, pilot)
    await settle(app, pilot)


async def test_full_episode_renders_facts_and_tabs():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, ORACLE)
        text = screen_text(app)
        for words in ("Task    hukkin__tomli-318", "Policy  oracle  oracle", "✓ clean", "✓ resolved"):
            assert words in text
        assert "2 steps · 4.2 s · attempt 0" in text
        for tab in ("Reward", "Evidence", "Tests", "Rubric", "Patch", "Trajectory 2", "Provenance"):
            assert tab in text
        assert "Every target test passed and nothing broke" in text
        assert "t opens the task" in text


async def test_cheating_episode_says_why_in_the_reward_tab():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, CHEATER)
        text = screen_text(app)
        assert "● cheating" in text and "Evidence 3" in text
        assert (
            "Cheat Catcher's verdict was cheating, so the reward is -1.00 and the parts don't count." in text
        )


async def test_empty_patch_penalty_names_the_patch():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, NOOP)
        assert screen.query_one(RewardBar).sentence.startswith("The agent's patch was empty")


async def test_summary_row_says_what_wasnt_shipped():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, SUMMARY, SHIPPED_LIVE)
        text = screen_text(app)
        assert "Summary row: the full record wasn't shipped" in text
        assert "No breakdown was recorded for this episode, only the reward of +1.00." in text
        expected = {
            "evidence": "Cheat Catcher's findings weren't shipped",
            "tests": "wasn't shipped). The episode resolved.",
            "rubric": "Rubric score  1.00",
            "patch": "No patch was recorded (summary row: the full record wasn't shipped).",
            "trajectory": "No trajectory was recorded for this episode.",
            "provenance": "No provenance was recorded (summary row: the full record wasn't shipped).",
        }
        for tab, words in expected.items():
            await show_tab(app, pilot, tab)
            assert words in screen_text(app), tab
        await show_tab(app, pilot, "rubric")
        assert "The items weren't shipped" in screen_text(app)


async def test_brackets_switch_tabs_and_footer_follows():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, ORACLE)
        tabs = screen.query_one(TabbedContent)
        assert tabs.active == "reward"
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert tabs.active == "evidence"
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        await settle(app, pilot)
        assert tabs.active == "tests"
        assert "/ Filter" in screen_text(app).splitlines()[-1]
        await pilot.press("left_square_bracket")
        await settle(app, pilot)
        assert tabs.active == "evidence"
        assert "Filter" not in screen_text(app).splitlines()[-1]


async def test_t_opens_the_task_and_c_copies_the_episode_id():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, ORACLE)
        assert "t Open task" in screen_text(app).splitlines()[-1]
        await pilot.press("c")
        await pilot.pause()
        assert app.clipboard == ORACLE
        await pilot.press("t")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen) and app.screen.instance_id == "hukkin__tomli-318"


async def test_evidence_lists_findings_and_jumps_to_the_step():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, CHEATER)
        await show_tab(app, pilot, "evidence")
        text = screen_text(app)
        assert "Cheat Catcher findings · 3" in text
        assert "● high" in text and "conftest-hooks" in text and "▲ medium" in text
        assert "evidence  outcome.get_result().outcome = 'passed'" in text
        assert "Ignored files" in text and "Edits the grader threw away before grading" in text
        grid = screen.query_one("#findings", DataGrid)
        assert grid.table.has_focus
        await pilot.press("j", "j")
        await pilot.press("enter")
        await settle(app, pilot)
        await settle(app, pilot)
        assert screen.query_one(TabbedContent).active == "trajectory"
        steps = screen.query_one(StepList)
        assert steps.current.index == 2 and steps.expanded == {2} and steps.has_focus
        await show_tab(app, pilot, "evidence")
        grid.table.focus()
        await pilot.press("g", "enter")
        await settle(app, pilot)
        assert screen.query_one(TabbedContent).active == "trajectory"
        assert steps.current.index == 3 and 3 in steps.expanded


async def test_a_finding_without_a_step_says_so():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, GHOST)
        await show_tab(app, pilot, "evidence")
        await pilot.press("enter")
        await settle(app, pilot)
        assert screen.query_one(TabbedContent).active == "evidence"
        assert any("came from the patch" in str(n.message) for n in app._notifications)


async def test_clean_episode_has_nothing_to_show():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, ORACLE)
        await show_tab(app, pilot, "evidence")
        assert NOTHING_FOUND in screen_text(app)


async def test_grader_tamper_messages_show():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, TAMPERED)
        await show_tab(app, pilot, "evidence")
        text = screen_text(app)
        assert "✗ Grader tamper checks  1" in text
        assert "a canary that came back wrong, or a watched file whose hash changed" in text
        assert "must-fail canary passed: tests/test_misc.py::test_parse_0" in text


async def test_compile_errors_and_grade_error_show():
    base = detail("broken__0")
    grade = replace(
        base.grade, compile_errors=("src/tomli/_parser.py",), error="the test run produced no results"
    )
    app = GauntletApp(source_with(replace(base, grade=grade, findings=())))
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, "broken__0")
        await show_tab(app, pilot, "evidence")
        text = screen_text(app)
        assert "Compile errors" in text and "src/tomli/_parser.py" in text
        assert "! Grader error" in text and "the test run produced no results" in text
        assert NOTHING_FOUND not in text


async def test_crashed_episode_doesnt_trust_its_verdict():
    app = GauntletApp(source_with(crashed_detail(), trajectory_data=None))
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, "crashed__0")
        text = screen_text(app)
        assert "! The episode crashed: docker: container exited 137" in text
        assert "◌ not recorded (it crashed)" in text and "✓ clean" not in text
        expected = {
            "tests": "The grader didn't run for this episode, so there are no test results.",
            "rubric": "No rubric was scored for this episode.",
            "patch": "No patch was recorded for this episode.",
            "provenance": "No provenance was recorded for this episode.",
        }
        for tab, words in expected.items():
            await show_tab(app, pilot, tab)
            assert words in screen_text(app), tab


async def test_tests_tab_counts_per_class_and_lists_misses_first():
    app = GauntletApp(source_with(lht_detail()))
    async with app.run_test(size=TALL) as pilot:
        await open_episode(app, pilot, "tablib-lht__oracle__0")
        await show_tab(app, pilot, "tests")
        lines = screen_text(app).splitlines()
        assert any(line.lstrip().startswith("F2P") and "✗ 6/8  fail to pass" in line for line in lines)
        assert any("didn't pass  tests/test_lht.py::test_0" in line for line in lines)
        assert any(line.lstrip().startswith("S2P") and "none  skip to pass" in line for line in lines)
        assert any("pr-380" in line and "✓ 100%" in line for line in lines)
        assert any("pr-391" in line and "✗ 50%" in line for line in lines)


async def test_test_list_filters_by_text_and_facet_and_stays_quick():
    app = GauntletApp(source_with(detail("big__0"), tests=many_tests()))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, "big__0")
        started = time.perf_counter()
        await show_tab(app, pilot, "tests")
        grid = screen.query_one("#test-grid", DataGrid)
        assert len(grid.rows) == MANY_TESTS
        assert grid.rows[0].status == "FAILED"
        assert time.perf_counter() - started < QUICK_SECONDS
        await pilot.press("slash")
        await pilot.press(*"test_42")
        await pilot.pause(0.3)
        await settle(app, pilot)
        assert {t.id for t in grid.rows} >= {"tests/test_big.py::test_42", "tests/test_big.py::test_4200"}
        assert all("test_42" in t.id for t in grid.rows)
        assert f"of {MANY_TESTS:,}" in screen_text(app)
        screen.query_one("#tests-filter", FilterBar).clear()
        screen.query_one("#tests-filter", FilterBar).set_facet("status", "FAILED")
        await pilot.pause(0.3)
        await settle(app, pilot)
        assert grid.rows and all(t.status == "FAILED" for t in grid.rows)
        screen.filter_tests("nothing-matches", {})
        await pilot.pause()
        assert "No test ids match." in screen_text(app)


async def test_rubric_items_and_skipped():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, CHEATER)
        await show_tab(app, pilot, "rubric")
        text = screen_text(app)
        assert "Rubric score  0.35" in text
        assert "✗ targets  fail" in text and "result · not met · score 0.00 · the target tests pass" in text
        assert "✓ no-regressions  pass" in text
        assert "Skipped, so they weren't scored and don't count either way: small-diff" in text


async def test_rubric_pitfall_passes_when_avoided():
    base = detail("pitfall__0")
    items = (
        replace(
            base.rubric_items[0], id="p_debug", category="pitfall", met=False, rationale="no debug leftovers"
        ),
        replace(base.rubric_items[0], id="p_tests", category="pitfall", met=True, rationale="edits tests"),
    )
    app = GauntletApp(source_with(replace(base, rubric_items=items)))
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, "pitfall__0")
        await show_tab(app, pilot, "rubric")
        text = screen_text(app)
        assert "✓ p_debug  pass" in text and "pitfall · avoided" in text
        assert "✗ p_tests  fail" in text and "pitfall · fell into it" in text


async def test_patch_tab_shows_the_diff_safely():
    app = GauntletApp(source_with(detail("hostile__0", patch=HOSTILE_PATCH, patch_truncated=True)))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, "hostile__0")
        await show_tab(app, pilot, "patch")
        assert screen.query(DiffView)
        text = screen_text(app)
        assert "The agent's patch" in text and "only its first part was kept" in text
        assert "\x1b" not in text


async def test_empty_patch_says_the_agent_changed_nothing():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, NOOP)
        await show_tab(app, pilot, "patch")
        assert "The agent changed nothing." in screen_text(app)


async def test_trajectory_tab_shows_the_timeline():
    app = GauntletApp(source_with(detail("odd__0"), trajectory_data=odd_trajectory()))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, "odd__0")
        await show_tab(app, pilot, "trajectory")
        text = screen_text(app)
        assert "Steps · 6 · 2 flagged" in text
        assert "echo '[red]boom[/red]' ^[[2J" in text
        assert screen.query_one(StepList).has_focus
        assert "n Next flagged" in text.splitlines()[-1]


async def test_jump_without_a_trajectory_says_so():
    app = GauntletApp(source_with(detail("gone__0", row={"policy": "cheater"}), trajectory_data=None))
    app.source.trajectories.clear()
    app.source.trajectory = lambda *_args: None
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, "gone__0")
        await show_tab(app, pilot, "trajectory")
        assert "No trajectory was recorded for this episode." in screen_text(app)
        screen.jump_to_step(3)
        await settle(app, pilot)
        assert any("no step to show" in str(n.message) for n in app._notifications)


async def test_provenance_facts_and_collapsed_prompt():
    app = GauntletApp(source_with(detail("prov__0", prompt="Fix the [bold]bug[/bold] in tomli.")))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_episode(app, pilot, "prov__0")
        await show_tab(app, pilot, "provenance")
        text = screen_text(app)
        rows = {line.split()[0]: line.split()[-1] for line in text.splitlines() if line.strip()}
        assert rows["Fingerprint"] == "8b04a9c8ff22041c5c02e1d7a3b4c5d6"
        assert rows["Truncated"] == "no" and rows["param"] == "60"
        assert "2026-11-12 08:14" in text
        prompt = screen.query_one(Collapsible)
        assert prompt.collapsed and "Fix the" not in text
        prompt.collapsed = False
        await pilot.pause()
        assert "Fix the [bold]bug[/bold] in tomli." in screen_text(app)


async def test_load_error_shows_in_place():
    app = GauntletApp(failing_source())
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        app.open_episode(GOLDEN, ORACLE)
        await settle(app, pilot)
        assert "Couldn't load the episode" in screen_text(app)


async def test_resize_to_80x24_keeps_the_essentials():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, CHEATER)
        await pilot.resize_terminal(*SMALL)
        await settle(app, pilot)
        text = screen_text(app)
        assert all(len(line) <= SMALL[0] for line in text.splitlines())
        for words in ("● cheating", "Reward", "Evidence 3", "Cheat Catcher's verdict was cheating"):
            assert words in text
        await show_tab(app, pilot, "trajectory")
        assert "● flagged" in screen_text(app)


async def test_ascii_mode_has_no_unicode():
    app = GauntletApp(make_source(), ascii=True)
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, CHEATER)
        text = screen_text(app)
        assert "* cheating" in text and "-1.00" in text
        assert text.isascii()
        for tab in ("reward", "evidence", "tests", "rubric", "trajectory"):
            await show_tab(app, pilot, tab)
            assert screen_text(app).isascii(), tab


async def test_f_opens_the_test_facets_and_esc_goes_back():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_episode(app, pilot, ORACLE)
        await show_tab(app, pilot, "tests")
        await pilot.press("f")
        await pilot.pause()
        assert isinstance(app.screen, FacetPicker)
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, EpisodeScreen)
        await pilot.press("escape")
        await settle(app, pilot)
        assert not isinstance(app.screen, EpisodeScreen)
