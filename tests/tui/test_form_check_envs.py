from dataclasses import replace
from pathlib import Path

import pytest
from textual.widgets import SelectionList

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.widgets.form import NO_WORKSPACE, FormView
from gauntlet.tui.widgets.jobstatus import command_line
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.base import task_sets
from gauntlet.tui.workbench.check_envs import CheckEnvs

from .factories import LHT, LIVE, make_source, screen_text
from .fakejobs import FakeJobRunner, fill, form_app, row_errors
from .test_job_screen import open_job
from .test_workbench import open_workbench, pick, settle

WIDE = (140, 40)
SMALL = (80, 24)
DRIFTED = 1


def flat(text: str) -> str:
    return "".join(text.replace("│", "").split())


def two_files(tmp_path: Path):
    """The sample data with a real, different task file for each set."""
    source = make_source()
    shown = []
    for dataset in source.datasets():
        folder = tmp_path / dataset.id
        folder.mkdir()
        (folder / "tasks.jsonl").write_text("")
        shown.append(replace(dataset, tasks_file=str(folder / "tasks.jsonl")))
    source.datasets = lambda: tuple(shown)  # type: ignore[method-assign]  # a test double
    return source


async def mounted(app, pilot) -> FormView:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app.query_one(FormView)


def test_it_is_found_and_lists_every_set_with_its_file():
    assert forms()["check_envs"] is CheckEnvs
    source = make_source()
    choices = task_sets(source)
    assert [(c.value, c.path) for c in choices] == [(d.id, d.tasks_file) for d in source.datasets()]
    assert all("task" in c.detail for c in choices)


async def test_nothing_is_picked_until_you_pick_and_one_is_needed(tmp_path: Path):
    app = form_app(CheckEnvs(), two_files(tmp_path), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        assert "A fingerprint hashes the install script" in screen_text(app)
        assert view.row("tasks").control.selected == []
        assert view.review() is None
        assert row_errors(view)["tasks"] == "Pick at least one of task sets."


async def test_it_builds_the_engines_command_for_several_sets(tmp_path: Path):
    source = two_files(tmp_path)
    files = {d.id: d.tasks_file for d in source.datasets()}
    app = form_app(CheckEnvs(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, tasks=(LIVE, LHT))
        spec = view.review()
        assert spec == actions.check_envs([files[LIVE], files[LHT]])
        assert spec.steps[0].argv[:2] == ("check-envs", "--tasks")


async def test_a_set_whose_file_is_gone_is_refused(tmp_path: Path):
    app = form_app(CheckEnvs(), make_source(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        control = view.row("tasks").control
        assert isinstance(control, SelectionList)
        control.select(control.get_option_at_index(0).value)
        assert view.review() is None
        assert "doesn't exist" in (view.banner.error or "")


async def test_the_confirm_step_shows_the_builders_command(tmp_path: Path):
    source = two_files(tmp_path)
    files = {d.id: d.tasks_file for d in source.datasets()}
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "check_envs")
        view = screen.forms["check_envs"]
        fill(view, tasks=(LIVE,))
        view.review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        text = screen_text(app)
        assert flat(f"$ {command_line(actions.check_envs([files[LIVE]]).steps[0])}") in flat(text)
        assert "network" in text and "not checked" in text


async def test_it_wont_start_before_the_machine_is_known(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = two_files(tmp_path)
    runner = FakeJobRunner()

    def broken():
        raise OSError("can't read free disk")

    monkeypatch.setattr(runner, "machine", broken)
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "check_envs")
        view = screen.forms["check_envs"]
        fill(view, tasks=(LIVE,))
        view.review()
        await settle(app, pilot)
        assert not isinstance(app.screen, ConfirmJob)
        assert view.banner.error == NO_WORKSPACE
        assert "Couldn't check the machine" in screen_text(app)
        assert runner.submitted == []


async def finished(tmp_path: Path, lines: list[str], exit_code: int) -> str:
    source = two_files(tmp_path)
    spec = actions.check_envs([d.tasks_file for d in source.datasets()])
    runner = FakeJobRunner()
    runner.script("check_envs", lines, exit_code=exit_code)
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await settle(app, pilot)
        return screen_text(app)


async def test_no_drift_reads_as_succeeded(tmp_path: Path):
    text = await finished(tmp_path, ["ok    hukkin__tomli-318 0123456789abcdef now 0123456789abcdef"], 0)
    assert "✓ succeeded" in text and "found something" not in text


async def test_drift_reads_as_found_something(tmp_path: Path):
    lines = ["ok    a 0123 now 0123", "DRIFT b 0123 now 4567", "DRIFT c 89ab now cdef"]
    text = await finished(tmp_path, lines, DRIFTED)
    assert "▲ found something" in text and "✗ failed" not in text
    assert "The check found 2 problems. The lines that start with DRIFT in the log say which." in text


async def test_a_clone_that_fails_reads_as_failed(tmp_path: Path):
    text = await finished(tmp_path, ["fatal: could not read from remote repository"], 1)
    assert "✗ failed" in text and "found something" not in text


async def test_fits_at_80_by_24(tmp_path: Path):
    app = GauntletApp(two_files(tmp_path), jobs=FakeJobRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "check_envs")
        await settle(app, pilot)
        assert screen.forms["check_envs"].has_class("-stacked")
        text = screen_text(app)
        assert "Task sets" in text and "Quit" in text.splitlines()[-1]


async def test_opening_it_on_a_task_set_picks_that_set(tmp_path: Path):
    source = two_files(tmp_path)
    app = form_app(CheckEnvs(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        view.prefill({"task_set": LHT})
        await pilot.pause()
        assert view.row("tasks").control.selected == [LHT]
        files = {d.id: d.tasks_file for d in source.datasets()}
        assert view.review() == actions.check_envs([files[LHT]])
