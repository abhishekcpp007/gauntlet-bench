import time
from dataclasses import replace

from gauntlet.tui.models import Trajectory
from gauntlet.tui.widgets.timeline import MAX_SHOWN_LINES, StepList, Timeline

from .episode_factories import HEADER, LHT_STEPS, LONG_OUTPUT_LINES, long_trajectory, odd_trajectory, step
from .factories import WidgetApp, screen_text

SIZE = (120, 30)
SMALL = (80, 24)
QUICK_SECONDS = 2.0
COMMAND_LINES = 1


async def test_rows_show_each_step():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "image gauntlet-harness-env:8b04a9c8ff22041c · network blocked · memory 512m · 1 CPU" in text
        lines = text.splitlines()
        assert any(line.lstrip().startswith("1  write_file   conftest.py") for line in lines)
        assert any("put_archive" in line for line in lines)
        assert "✗ 2" in text
        assert "▲ timed out" in text and "◌ truncated" in text
        assert "● flagged outcome-forcing, conftest-hooks" in text
        assert "● flagged shell-test-edit" in text


async def test_untrusted_command_shows_literally():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        steps = app.query_one(StepList)
        steps.focus()
        await pilot.press("enter")
        await pilot.pause()
        text = screen_text(app)
        assert "echo '[red]boom[/red]' ^[[2J && rm -rf /" in text
        assert "^[[31m[bold]FAILED[/bold]^[[0m" in text
        assert "\x1b" not in text


async def test_expand_and_collapse():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        steps = app.query_one(StepList)
        steps.focus()
        await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()
        assert steps.expanded == {1}
        text = screen_text(app)
        assert "path     conftest.py" in text and "content  import pytest" in text
        await pilot.press("space")
        await pilot.pause()
        assert steps.expanded == set()
        assert "content  import pytest" not in screen_text(app)


async def test_long_output_is_capped_behind_show_more():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=(120, 60)) as pilot:
        await pilot.pause()
        steps = app.query_one(StepList)
        steps.focus()
        await pilot.press("j", "j", "enter")
        await pilot.pause()
        shown = [line for line in steps.lines if line.step == 2 and line.kind in ("label", "text")]
        assert len(shown) == MAX_SHOWN_LINES + COMMAND_LINES
        hidden = LONG_OUTPUT_LINES - MAX_SHOWN_LINES
        assert f"{hidden} more lines in stdout" in screen_text(app)
        await pilot.press("m")
        await pilot.pause()
        shown = [line for line in steps.lines if line.step == 2 and line.kind in ("label", "text")]
        assert len(shown) == LONG_OUTPUT_LINES + COMMAND_LINES
        await pilot.press("m")
        await pilot.pause()
        shown = [line for line in steps.lines if line.step == 2 and line.kind in ("label", "text")]
        assert len(shown) == MAX_SHOWN_LINES + COMMAND_LINES


async def test_next_and_previous_flagged():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        steps = app.query_one(StepList)
        steps.focus()
        await pilot.press("n")
        assert steps.current.index == 4
        await pilot.press("n")
        assert steps.current.index == 5
        await pilot.press("n")
        assert steps.current.index == 4
        await pilot.press("N")
        assert steps.current.index == 5
        await pilot.press("g")
        await pilot.press("N")
        assert steps.current.index == 5


async def test_no_flagged_steps_says_so():
    app = WidgetApp(Timeline(Trajectory(header=HEADER, steps=(step(0), step(1)))))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        app.query_one(StepList).focus()
        await pilot.press("n")
        await pilot.pause()
        assert any("No step was flagged" in str(n.message) for n in app._notifications)


async def test_show_step_scrolls_and_expands():
    timeline = Timeline(long_trajectory())
    app = WidgetApp(timeline)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        assert timeline.show_step(250)
        await pilot.pause()
        steps = app.query_one(StepList)
        assert steps.current.index == 250 and steps.expanded == {250}
        assert steps.scroll_offset.y > 0
        assert "250  exec" in screen_text(app)
        assert not timeline.show_step(LHT_STEPS + 1)


async def test_open_step_from_the_constructor():
    app = WidgetApp(Timeline(long_trajectory(), open_step=300))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        steps = app.query_one(StepList)
        assert steps.has_focus and steps.current.index == 300 and 300 in steps.expanded
        assert "300  exec" in screen_text(app)


async def test_400_steps_render_and_move_quickly():
    app = WidgetApp(Timeline(long_trajectory()))
    async with app.run_test(size=SIZE) as pilot:
        started = time.perf_counter()
        await pilot.pause()
        steps = app.query_one(StepList)
        steps.focus()
        await pilot.press("G")
        await pilot.pause()
        assert steps.current.index == LHT_STEPS - 1
        assert f"{LHT_STEPS - 1}  exec" in screen_text(app)
        assert time.perf_counter() - started < QUICK_SECONDS


async def test_narrow_drops_the_time_column():
    app = WidgetApp(Timeline(odd_trajectory()))
    async with app.run_test(size=SMALL) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert all(len(line) <= SMALL[0] for line in text.splitlines())
        assert "time" not in text.splitlines()[1]
        assert "● flagged" in text


async def test_open_network_and_warnings_are_marked():
    header = replace(HEADER, network=True, cpus=2.0)
    app = WidgetApp(
        Timeline(Trajectory(header=header, steps=(step(0),), warnings=("Skipped line 3: [bad]",)))
    )
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "▲ network open" in text and "2 CPUs" in text
        assert "▲ Skipped line 3: [bad]" in text


async def test_no_steps_and_no_header():
    app = WidgetApp(Timeline(Trajectory(header=None, steps=())))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "No sandbox header was recorded." in text
        assert "The trajectory has no steps." in text


async def test_ascii_marks():
    app = WidgetApp(Timeline(odd_trajectory()), ascii=True)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "* flagged" in text and "x 2" in text
        assert text.isascii()
