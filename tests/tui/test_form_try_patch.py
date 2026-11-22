from dataclasses import replace
from pathlib import Path

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.screens.episode import EpisodeScreen
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.widgets.form import FormView
from gauntlet.tui.widgets.jobstatus import command_line
from gauntlet.tui.widgets.pickers import Picker
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.try_patch import MAKE_A_PATCH, TryPatch
from gauntlet.tui.workspace import Workspace

from .factories import screen_text
from .fakejobs import FakeJobRunner, fake_machine, fill, form_app, row_errors
from .sample import LIVE_ID, RUN_ID, TOMLI, sample_store
from .test_actions import HONEST_DIFF
from .test_job_screen import open_job
from .test_workbench import open_workbench, pick, settle

WIDE = (140, 40)
SMALL = (80, 24)
RUN_NAME = "try-mine"
SOLVED = "patch:mine.diff  hukkin__tomli-318  SOLVED reward=+1.000 cheat=clean"


def flat(text: str) -> str:
    return "".join(text.replace("│", "").split())


def a_patch(tmp_path: Path, body: str | None = None) -> Path:
    path = tmp_path / "mine.diff"
    path.write_text(HONEST_DIFF.read_text() if body is None else body)
    return path


async def mounted(app, pilot) -> FormView:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app.query_one(FormView)


def test_it_is_found():
    assert forms()["try_patch"] is TryPatch


async def test_it_builds_the_engines_command(tmp_path: Path):
    source = sample_store()
    patch = a_patch(tmp_path)
    app = form_app(TryPatch(), source, workspace=tmp_path / "ws")
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        assert flat(MAKE_A_PATCH) in flat(screen_text(app))
        fill(view, tasks=LIVE_ID)
        await pilot.pause()
        fill(view, task=TOMLI, patch=patch)
        spec = view.review()
        assert spec is not None
        tasks = next(d.tasks_file for d in source.datasets() if d.id == LIVE_ID)
        name = Path(spec.outputs[0].path).name
        assert spec == actions.try_patch(Workspace(tmp_path / "ws"), tasks, TOMLI, patch, name=name)
        assert spec.outputs[0].episode_id is not None


async def test_the_task_picker_lists_only_the_chosen_sets_tasks(tmp_path: Path):
    app = form_app(TryPatch(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        control = view.row("task").control
        assert isinstance(control, Picker)
        fill(view, tasks=LIVE_ID)
        await pilot.pause()
        assert {c.value for c in control.fetch()} == {
            t.instance_id for t in sample_store().tasks(dataset=LIVE_ID)
        }


async def test_a_missing_or_empty_patch_gets_one_clear_line(tmp_path: Path):
    app = form_app(TryPatch(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, tasks=LIVE_ID)
        await pilot.pause()
        fill(view, task=TOMLI, patch=tmp_path / "gone.diff")
        assert view.review() is None
        assert row_errors(view) == {"patch": f"There's no file at {tmp_path / 'gone.diff'}."}
        empty = a_patch(tmp_path, " \n")
        fill(view, patch=empty)
        assert view.review() is None
        assert row_errors(view) == {"patch": f"{empty} is empty. {MAKE_A_PATCH}"}


async def test_every_field_is_needed(tmp_path: Path):
    app = form_app(TryPatch(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        assert view.review() is None
        assert set(row_errors(view)) == {"tasks", "task", "patch"}


async def test_the_confirm_step_shows_the_builders_command(tmp_path: Path):
    patch = a_patch(tmp_path)
    app = GauntletApp(sample_store(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "try_patch")
        view = screen.forms["try_patch"]
        view.workspace = Workspace(tmp_path / "ws")
        fill(view, tasks=LIVE_ID)
        await pilot.pause()
        fill(view, task=TOMLI, patch=patch)
        spec = view.review()
        await pilot.pause()
        assert spec is not None and isinstance(app.screen, ConfirmJob)
        assert flat(f"$ {command_line(spec.steps[0])}") in flat(screen_text(app))


async def test_no_docker_blocks_it(tmp_path: Path):
    runner = FakeJobRunner(machine=fake_machine(docker_running=False, docker_detail="no daemon"))
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "try_patch")
        view = screen.forms["try_patch"]
        view.workspace = Workspace(tmp_path / "ws")
        fill(view, tasks=LIVE_ID)
        await pilot.pause()
        fill(view, task=TOMLI, patch=a_patch(tmp_path))
        assert view.review() is None
        assert "Docker isn't running (no daemon)" in screen_text(app)
        assert runner.submitted == []


def try_spec(tmp_path: Path):
    source = sample_store()
    tasks = next(d.tasks_file for d in source.datasets() if d.id == LIVE_ID)
    workspace = Workspace(tmp_path / "ws")
    return source, actions.try_patch(workspace, tasks, TOMLI, a_patch(tmp_path), name=RUN_NAME)


async def test_a_run_that_isnt_loaded_yet_is_never_guessed_from_its_name(tmp_path: Path, monkeypatch):
    source, spec = try_spec(tmp_path)
    runner = FakeJobRunner()
    runner.script("try_patch", [SOLVED])
    app = GauntletApp(source, jobs=runner)
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "✓ succeeded" in text and "Open" in text.splitlines()[-1]
        await pilot.press("o")
        await settle(app, pilot)
        assert not isinstance(app.screen, EpisodeScreen)
        assert said and "isn't loaded yet" in said[-1]


async def test_a_loaded_run_is_found_by_its_folder(tmp_path: Path, monkeypatch):
    source, spec = try_spec(tmp_path)
    runs = source.runs()
    moved = tuple(replace(r, path=spec.outputs[0].path) if r.id == RUN_ID else r for r in runs)
    monkeypatch.setattr(source, "runs", lambda: moved)
    runner = FakeJobRunner()
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen) and app.screen.run_id == RUN_ID


async def test_a_failed_try_stays_on_the_job_and_says_so(tmp_path: Path):
    source, spec = try_spec(tmp_path)
    runner = FakeJobRunner()
    runner.script("try_patch", [("error: patch does not apply", "err")], exit_code=1)
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "✗ failed" in text and "found something" not in text
        assert "patch does not apply" in text
        await pilot.press("o")
        await settle(app, pilot)
        assert not isinstance(app.screen, EpisodeScreen)


async def test_fits_at_80_by_24(tmp_path: Path):
    app = GauntletApp(sample_store(), jobs=FakeJobRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "try_patch")
        await settle(app, pilot)
        assert screen.forms["try_patch"].has_class("-stacked")
        text = screen_text(app)
        assert "Task set" in text and "Quit" in text.splitlines()[-1]
        assert isinstance(app.screen, type(screen)) and not isinstance(app.screen, JobScreen)
