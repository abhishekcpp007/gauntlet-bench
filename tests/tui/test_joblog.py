import time

from gauntlet.tui.widgets.joblog import JobLog, LogLines, split_lines

from .factories import WidgetApp, screen_text

SIZE = (80, 24)
MANY = 50_000
WINDOW = 1_000
FAST_ENOUGH = 2.0
HOSTILE = "[red]x[/red] \x1b[31mred\x1b[0m done"


def test_a_carriage_return_starts_the_line_over():
    assert split_lines("one\ntwo\r\n") == ["one", "two"]
    assert split_lines("10%\r50%\r100%") == ["100%"]
    assert split_lines("") == [""]


async def test_untrusted_text_shows_literally():
    log = JobLog()
    async with WidgetApp(log).run_test(size=SIZE) as pilot:
        log.write([(HOSTILE, "out")])
        await pilot.pause()
        text = screen_text(pilot.app)
        assert "[red]x[/red] ^[[31mred^[[0m done" in text
        assert "\x1b" not in text


async def test_stderr_carries_a_mark_stdout_does_not():
    log = JobLog()
    async with WidgetApp(log).run_test(size=SIZE) as pilot:
        log.write([("from stdout", "out"), ("from stderr", "err")])
        await pilot.pause()
        lines = screen_text(pilot.app).splitlines()
        out = next(line for line in lines if "from stdout" in line)
        err = next(line for line in lines if "from stderr" in line)
        assert out.startswith("  from stdout")
        assert err.startswith("▌ from stderr")


async def test_keeps_a_bounded_window_and_says_where_the_rest_is():
    log = JobLog(window=WINDOW, log_path="gauntlet-work/jobs/7/log.txt")
    async with WidgetApp(log).run_test(size=SIZE) as pilot:
        started = time.perf_counter()
        log.write((f"line {n}", "out") for n in range(MANY))
        await pilot.pause()
        assert time.perf_counter() - started < FAST_ENOUGH
        lines = log.lines
        assert len(lines.lines) == WINDOW and lines.total == MANY and lines.truncated
        text = screen_text(pilot.app)
        assert f"line {MANY - 1}" in text
        lines.scroll_home(animate=False)
        await pilot.pause()
        assert "Earlier lines are only in the log file: gauntlet-work/jobs/7/log.txt" in screen_text(
            pilot.app
        )


async def test_follows_new_output_until_you_scroll_up():
    log = JobLog()
    async with WidgetApp(log).run_test(size=SIZE) as pilot:
        log.write((f"line {n}", "out") for n in range(100))
        await pilot.pause()
        log.lines.focus()
        assert "line 99" in screen_text(pilot.app)
        await pilot.press("k")
        assert not log.follow
        log.write([("line 100", "out")])
        await pilot.pause()
        assert "line 100" not in screen_text(pilot.app)
        await pilot.press("G")
        await pilot.pause()
        assert log.follow and "line 100" in screen_text(pilot.app)
        log.toggle_follow()
        assert not log.follow


async def test_search_finds_and_steps_through_matches():
    log = JobLog()
    async with WidgetApp(log).run_test(size=SIZE) as pilot:
        log.write((f"line {n}" + (" needle" if n in (10, 60) else ""), "out") for n in range(100))
        await pilot.pause()
        log.open_search()
        await pilot.press(*"NEEDLE")
        await pilot.pause()
        assert log.lines.match == 10 and not log.follow
        assert "line 10 needle" in screen_text(pilot.app)
        await pilot.press("enter", "n")
        await pilot.pause()
        assert log.lines.match == 60
        await pilot.press("N")
        assert log.lines.match == 10
        log.open_search()
        await pilot.press("escape")
        assert log.lines.needle == "" and isinstance(pilot.app.focused, LogLines)


async def test_a_missing_word_finds_nothing():
    log = JobLog()
    async with WidgetApp(log).run_test(size=SIZE):
        log.write([("alpha", "out")])
        assert not log.lines.find("omega")
        assert log.lines.match == -1
