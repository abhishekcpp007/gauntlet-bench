from dataclasses import replace
from pathlib import Path

import pytest

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.widgets.form import FormBanner, FormView
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.base import ActionForm, register
from gauntlet.tui.workbench.calibrate import Calibrate
from gauntlet.tui.workbench.scan import ScanPatch
from gauntlet.tui.workspace import Workspace

from .factories import LIVE, FakeSource, make_source, screen_text
from .fakejobs import FakeJobRunner, fill, form_app, row_errors
from .test_form import capture_reviews

SIZE = (120, 40)


def source_with_files(tmp_path: Path) -> tuple[FakeSource, Path]:
    """The sample data, with every task set's file really there."""
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("")
    source = make_source()
    shown = tuple(replace(d, tasks_file=str(tasks)) for d in source.datasets())
    source.datasets = lambda: shown  # type: ignore[method-assign]  # a test double
    return source, tasks


def test_every_form_is_found_and_matches_an_engine_action():
    found = forms()
    assert found["scan_patch"] is ScanPatch and found["calibrate"] is Calibrate
    assert set(found) <= {info.id for info in actions.ACTIONS}


def test_a_form_must_name_an_engine_action_and_only_once():
    class Unknown(ActionForm):
        action_id = "make_coffee"

    class Second(ActionForm):
        action_id = ScanPatch.action_id

    with pytest.raises(ValueError, match="isn't one of the actions"):
        register(Unknown)
    with pytest.raises(ValueError, match="two forms"):
        register(Second)


async def test_scan_builds_the_engines_command(tmp_path: Path, monkeypatch):
    patch = tmp_path / "fix.diff"
    patch.write_text("diff")
    trajectory = tmp_path / "steps.jsonl"
    trajectory.write_text("")
    app = form_app(ScanPatch(), workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        posted = capture_reviews(view, monkeypatch)
        fill(view, patch=patch, protect="tests/test_a.py, tests/test_b.py", trajectory=trajectory)
        spec = view.review()
        assert spec is not None and posted == [spec]
        protect = ("tests/test_a.py", "tests/test_b.py")
        assert spec == actions.scan_patch(patch, protect=protect, trajectory=trajectory)


async def test_scan_shows_the_builders_refusal(tmp_path: Path):
    patch = tmp_path / "fix.diff"
    patch.write_text("diff")
    app = form_app(ScanPatch(), workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, patch=patch, protect="-rf")
        assert view.review() is None
        await pilot.pause()
        error = view.query_one(FormBanner).error
        assert error is not None and "-rf" in error
        assert "Can't build this job" in screen_text(app)


async def test_scan_needs_a_patch_that_exists(tmp_path: Path):
    app = form_app(ScanPatch(), workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, patch=tmp_path / "missing.diff")
        assert view.review() is None
        assert "no file" in row_errors(view)["patch"]


async def test_calibrate_hands_the_task_sets_file_to_the_builder(tmp_path: Path):
    source, tasks = source_with_files(tmp_path)
    app = form_app(Calibrate(), source, workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE, sample="0", seed="nightly", policies=("oracle", "noop"), workers="4")
        spec = view.review()
        assert spec is not None
        argv = spec.steps[0].argv
        assert argv[:3] == ("calibrate", "--tasks", str(tasks.resolve()))
        assert argv[argv.index("--seed") + 1] == "nightly"
        assert argv[argv.index("--policies") + 1] == "oracle,noop"
        assert argv[argv.index("--workers") + 1] == "4"
        assert spec.outputs[0].kind == "run"
        assert Path(spec.outputs[0].path).is_relative_to(tmp_path.resolve())


async def test_calibrate_defaults_to_every_policy_and_checks_its_numbers(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = form_app(Calibrate(), source, workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE)
        spec = view.review()
        assert spec is not None
        argv = spec.steps[0].argv
        assert argv[argv.index("--policies") + 1].split(",") == list(actions.CALIBRATION_POLICIES)
        assert "api_key" not in spec.needs
        fill(view, workers="0", sample="-1")
        assert view.review() is None
        assert set(row_errors(view)) == {"workers", "sample"}


async def test_calibrate_refuses_a_task_set_whose_file_is_gone(tmp_path: Path):
    app = form_app(Calibrate(), workspace=tmp_path)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE)
        assert view.review() is None
        await pilot.pause()
        error = view.query_one(FormBanner).error
        assert error is not None and "task file" in error.lower()


async def test_calibrate_in_the_workbench_shows_its_command_before_it_runs(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.screen.forms["calibrate"]
        view.workspace = Workspace(tmp_path)
        fill(view, tasks=LIVE)
        view.review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        assert "gauntlet calibrate --tasks" in screen_text(app)
