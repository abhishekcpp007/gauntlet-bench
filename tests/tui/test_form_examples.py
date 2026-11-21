from pathlib import Path

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.widgets.form import FormView
from gauntlet.tui.workbench import catalogue
from gauntlet.tui.workbench.base import ActionForm, register
from gauntlet.tui.workbench.calibrate import Calibrate, tasks_file
from gauntlet.tui.workbench.scan import ScanPatch

from .factories import LIVE, make_source, screen_text
from .test_form import capture_reviews
from .workfakes import WORKSPACE, ScriptedRunner, fill, form_app, row_errors

SIZE = (120, 40)


def test_both_examples_are_registered_in_their_groups():
    forms = catalogue()
    assert Calibrate in forms and ScanPatch in forms
    assert forms.index(Calibrate) < forms.index(ScanPatch)


def test_two_actions_cant_share_an_id():
    class Copy(ActionForm):
        action_id = ScanPatch.action_id
        title = "Copy"
        group = "score"
        description = "A second scan."

    try:
        register(Copy)
    except ValueError as error:
        assert "two actions" in str(error)
    else:
        raise AssertionError("a duplicate id was registered")


def test_a_made_task_set_is_read_from_the_workspace(tmp_path: Path):
    made = tmp_path / "tasks" / "click" / "tasks.jsonl"
    made.parent.mkdir(parents=True)
    made.write_text("")
    assert tasks_file("click", tmp_path) == made
    assert tasks_file("live-2026-11", tmp_path) == Path("datasets/gauntlet-live-2026-11/tasks.jsonl")


async def test_scan_builds_the_cheatcatcher_command(tmp_path: Path, monkeypatch):
    patch = tmp_path / "fix.diff"
    patch.write_text("diff")
    trajectory = tmp_path / "steps.jsonl"
    trajectory.write_text("")
    app = form_app(ScanPatch())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        posted = capture_reviews(view, monkeypatch)
        fill(view, patch=patch, protect="tests/test_a.py, tests/test_b.py", trajectory=trajectory)
        spec = view.review()
        assert spec is not None and posted == [spec]
        assert spec.steps[0].argv == (
            "cheatcatcher",
            "scan",
            "--patch",
            str(patch),
            "--protect",
            "tests/test_a.py",
            "tests/test_b.py",
            "--trajectory",
            str(trajectory),
            "--json",
        )
        assert spec.needs == () and not spec.exclusive and spec.title == "Scan fix.diff"


async def test_scan_needs_a_patch_that_exists(tmp_path: Path):
    app = form_app(ScanPatch())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, patch=tmp_path / "missing.diff")
        assert view.review() is None
        assert "no file" in row_errors(view)["patch"]


async def test_calibrate_builds_the_command_with_its_options():
    app = form_app(Calibrate(), workspace=Path(WORKSPACE))
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE, sample="0", seed="nightly", policies=("oracle", "cheater"), workers="4")
        spec = view.review()
        assert spec is not None
        argv = spec.steps[0].argv
        assert argv[:3] == ("calibrate", "--tasks", f"datasets/{LIVE}/tasks.jsonl")
        assert "--sample" not in argv
        assert argv[3:9] == ("--seed", "nightly", "--policies", "oracle,cheater", "--workers", "4")
        assert argv[9] == "-o" and argv[10].startswith(f"{WORKSPACE}/runs/calibrate-{LIVE}-")
        assert spec.needs == ("docker",) and spec.exclusive
        assert spec.outputs[0].kind == "run" and spec.outputs[0].path == argv[10]


async def test_calibrate_defaults_to_every_policy_and_checks_its_numbers():
    app = form_app(Calibrate())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, tasks=LIVE)
        spec = view.review()
        assert spec is not None
        policies = spec.steps[0].argv[spec.steps[0].argv.index("--policies") + 1].split(",")
        assert policies == [p.id for p in make_source().reference().policies]
        assert "--sample" in spec.steps[0].argv
        fill(view, workers="0", sample="-1")
        assert view.review() is None
        assert set(row_errors(view)) == {"workers", "sample"}


async def test_calibrate_in_the_workbench_shows_its_command_before_it_runs():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await pilot.press("5")
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        fill(app.screen.forms["calibrate"], tasks=LIVE)
        app.screen.forms["calibrate"].review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        assert "gauntlet calibrate --tasks" in screen_text(app)
