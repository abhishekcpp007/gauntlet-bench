from pathlib import Path

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.widgets.form import FormBanner, FormView
from gauntlet.tui.widgets.jobstatus import command_line
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.leakcheck import LeakCheck
from gauntlet.tui.workspace import Workspace

from .factories import LIVE, make_source, screen_text
from .fakejobs import FakeJobRunner, fake_machine, fill, form_app, row_errors
from .test_form_examples import source_with_files
from .test_job_screen import open_job
from .test_workbench import open_workbench, pick, settle

WIDE = (140, 40)
SMALL = (80, 24)
FOUND_A_LEAK = 1


def flat(text: str) -> str:
    return "".join(text.replace("│", "").split())


async def test_it_is_found_and_says_what_the_checks_look_for(tmp_path: Path):
    assert forms()["leakcheck"] is LeakCheck
    app = form_app(LeakCheck(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert f"all {actions.LEAK_CHECK_COUNT} checks" in text
        assert "anywhereanagentcouldreadthem" in flat(text)


async def test_it_builds_the_engines_command(tmp_path: Path):
    source, tasks = source_with_files(tmp_path)
    app = form_app(LeakCheck(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE)
        assert view.review() == actions.leakcheck(tasks)


async def test_it_needs_a_task_set_with_a_file(tmp_path: Path):
    app = form_app(LeakCheck(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        assert view.review() is None
        assert row_errors(view)["tasks"] == "Task set is needed."
        fill(view, tasks=LIVE)
        assert view.review() is None
        error = view.query_one(FormBanner).error
        assert error is not None and "doesn't exist" in error


async def test_the_confirm_step_shows_the_builders_command(tmp_path: Path):
    source, tasks = source_with_files(tmp_path)
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "leakcheck")
        view = screen.forms["leakcheck"]
        view.workspace = Workspace(tmp_path)
        fill(view, tasks=LIVE)
        view.review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        expected = command_line(actions.leakcheck(tasks).steps[0])
        assert flat(f"$ {expected}") in flat(screen_text(app))
        assert "✓ Docker" in screen_text(app)


async def test_no_docker_blocks_it_and_says_why(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    machine = fake_machine(docker_running=False, docker_detail="Cannot connect to the Docker daemon")
    runner = FakeJobRunner(machine=machine)
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "leakcheck")
        view = screen.forms["leakcheck"]
        fill(view, tasks=LIVE)
        assert view.review() is None
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmJob)
        assert "Docker isn't running (Cannot connect to the Docker daemon)" in screen_text(app)
        assert runner.submitted == []


async def finished(tmp_path: Path, lines: list[str], exit_code: int) -> str:
    _, tasks = source_with_files(tmp_path)
    runner = FakeJobRunner()
    runner.script("leakcheck", lines, exit_code=exit_code)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(actions.leakcheck(tasks))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await settle(app, pilot)
        return screen_text(app)


async def test_a_clean_set_reads_as_succeeded(tmp_path: Path):
    text = await finished(tmp_path, ["ok   hukkin__tomli-318 ", "ok   mahmoud__boltons-471 "], 0)
    assert "✓ succeeded" in text and "found something" not in text


async def test_a_leak_reads_as_found_something_not_a_crash(tmp_path: Path):
    lines = ["ok   hukkin__tomli-318 ", "LEAK mahmoud__boltons-471 statement, gold_on_disk"]
    text = await finished(tmp_path, lines, FOUND_A_LEAK)
    assert "▲ found something" in text and "✗ failed" not in text
    assert "The check found 1 problem. The lines that start with LEAK in the log say which." in text


async def test_a_crash_reads_as_failed(tmp_path: Path):
    text = await finished(tmp_path, ["Traceback (most recent call last):", "OSError: disk full"], 1)
    assert "✗ failed" in text and "found something" not in text


async def test_fits_at_80_by_24(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "leakcheck")
        await settle(app, pilot)
        assert screen.forms["leakcheck"].has_class("-stacked")
        text = screen_text(app)
        assert "Task set" in text and "Quit" in text.splitlines()[-1]
