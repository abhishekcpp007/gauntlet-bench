from pathlib import Path

import pytest

from gauntlet.tui.app import NO_WORKBENCH, GauntletApp
from gauntlet.tui.jobtypes import JobSpec
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.overview import OverviewScreen
from gauntlet.tui.screens.workbench import ActionList, NoForm, WorkbenchScreen, machine_line
from gauntlet.tui.theme import make_look
from gauntlet.tui.widgets.form import FormView, ReviewButton
from gauntlet.tui.widgets.pickers import PathPicker, Picker
from gauntlet.tui.workbench.base import (
    ActionForm,
    PathField,
    RunField,
    TaskField,
    TaskSetField,
    TextField,
    Values,
    place_prefill,
)
from gauntlet.tui.workbench.calibrate import Calibrate

from .factories import GOLDEN, LHT, LIVE, LIVE_JS, make_source, screen_text
from .fakejobs import FakeJobRunner, fake_machine, make_spec

WIDE = (140, 40)
SMALL = (80, 24)
TOMLI = "hukkin__tomli-318"
MAGIC = "Rich-Harris__magic-string-379"
DEPTH = 20


class TryPatchForm(ActionForm):
    action_id = "try_patch"
    fields = (
        TextField(name="label", label="Label", required=False),
        TaskSetField(name="tasks", label="Task set"),
        TaskField(name="instance", label="Task", task_set="tasks"),
        PathField(name="diff", label="Patch file"),
    )

    def build(self, values: Values) -> JobSpec:
        return make_spec(action=self.action_id)


class ReportForm(ActionForm):
    action_id = "report"
    fields = (
        PathField(name="out", label="Report folder", kind="folder", must_exist=False),
        RunField(name="results", label="Run", results=True),
    )

    def build(self, values: Values) -> JobSpec:
        return make_spec(action=self.action_id)


FORMS: dict[str, type[ActionForm]] = {
    "try_patch": TryPatchForm,
    "report": ReportForm,
    "calibrate": Calibrate,
}


def workbench_app(runner: FakeJobRunner | None = None) -> GauntletApp:
    return GauntletApp(make_source(), jobs=runner or FakeJobRunner(), forms=FORMS)


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)
    await app.workers.wait_for_complete()
    await pilot.pause()


async def opened(app: GauntletApp, pilot, action_id: str, **prefill: str) -> WorkbenchScreen:
    await settle(app, pilot)
    app.open_workbench(action_id, **prefill)
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, WorkbenchScreen)
    return screen


def picked(view: FormView, name: str) -> str | None:
    control = view.row(name).control
    assert isinstance(control, Picker)
    return control.value


def typed(view: FormView, name: str) -> str:
    control = view.row(name).control
    assert isinstance(control, PathPicker)
    return control.value


def test_prefill_goes_to_the_first_field_of_its_kind():
    placed = place_prefill(
        TryPatchForm.fields + ReportForm.fields,
        {"task_set": LIVE, "task": TOMLI, "patch": "fix.diff", "run": GOLDEN, "colour": "red"},
    )
    assert {key: (field.name, value) for key, (field, value) in placed.items()} == {
        "task_set": ("tasks", LIVE),
        "task": ("instance", TOMLI),
        "patch": ("diff", "fix.diff"),
        "run": ("results", GOLDEN),
    }


def test_a_patch_never_lands_in_a_folder_field():
    assert place_prefill(ReportForm.fields, {"patch": "fix.diff"}) == {}


async def test_open_workbench_picks_the_action_and_fills_each_kind(tmp_path: Path):
    patch = tmp_path / "fix.diff"
    patch.write_text("")
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "try_patch", task_set=LIVE_JS, task=MAGIC, patch=str(patch))
        assert screen.current == "try_patch"
        options = screen.query_one(ActionList)
        assert options.highlighted == options.get_option_index("try_patch")
        view = screen.forms["try_patch"]
        assert picked(view, "tasks") == LIVE_JS
        assert picked(view, "instance") == MAGIC
        assert typed(view, "diff") == str(patch)
        assert isinstance(app.focused, ReviewButton)
        assert view.review() is not None


async def test_a_task_alone_brings_its_task_set():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "try_patch", task=TOMLI)
        view = screen.forms["try_patch"]
        assert picked(view, "tasks") == LIVE
        assert picked(view, "instance") == TOMLI
        assert app.focused in view.row("diff").query("*")


async def test_a_run_fills_the_run_picker():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "report", run=GOLDEN)
        assert picked(screen.forms["report"], "results") == GOLDEN
        assert typed(screen.forms["report"], "out") == ""


async def test_unknown_keys_and_values_are_left_alone():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "try_patch", task_set="no-such-set", colour="red")
        view = screen.forms["try_patch"]
        assert picked(view, "tasks") is None
        assert picked(view, "instance") is None
        assert view.row("label").raw == ""
        assert app.focused in view.row("tasks").query("*") or app.focused is view.row("tasks").control


async def test_a_second_prefill_replaces_the_first():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "try_patch", task=TOMLI)
        await pilot.press("2")
        await settle(app, pilot)
        app.open_workbench("try_patch", task_set=LHT)
        await settle(app, pilot)
        view = screen.forms["try_patch"]
        assert picked(view, "tasks") == LHT
        assert picked(view, "instance") is None


async def test_an_action_without_a_form_shows_its_note():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "leakcheck", task_set=LIVE)
        assert screen.current == "leakcheck"
        assert isinstance(screen.query_one("#forms").visible_content, NoForm)
        assert "doesn't have a form in the Workbench yet" in screen_text(app)
        assert isinstance(app.focused, ActionList)


async def test_an_unknown_action_changes_nothing():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "calibrate")
        app.open_workbench("no_such_action", task=TOMLI)
        await settle(app, pilot)
        assert screen.current == "calibrate"


async def test_without_a_runner_it_only_says_the_workbench_is_off(monkeypatch: pytest.MonkeyPatch):
    app = GauntletApp(make_source(), forms=FORMS)
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_kw: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_workbench("try_patch", task=TOMLI)
        await settle(app, pilot)
        assert isinstance(app.screen, OverviewScreen)
        assert said == [NO_WORKBENCH]


async def test_it_comes_back_from_a_job_screen_on_the_workbench():
    runner = FakeJobRunner()
    job = runner.seed(make_spec())
    app = workbench_app(runner)
    async with app.run_test(size=WIDE) as pilot:
        await opened(app, pilot, "calibrate")
        app.open_job(job.id)
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen)
        screen = await opened(app, pilot, "try_patch", task=TOMLI)
        assert len(app.screen_stack) == 1
        assert picked(screen.forms["try_patch"], "instance") == TOMLI


async def test_the_jobs_tab_gives_way_to_the_actions():
    app = workbench_app()
    async with app.run_test(size=WIDE) as pilot:
        screen = await opened(app, pilot, "calibrate")
        screen.show_tab("jobs")
        await settle(app, pilot)
        app.open_workbench("calibrate", task_set=LHT)
        await settle(app, pilot)
        assert screen.query_one("#wb-tabs").active == "actions"
        assert picked(screen.forms["calibrate"], "tasks") == LHT


@pytest.mark.parametrize("size", [WIDE, SMALL])
async def test_the_machine_line_shows_the_workspace_path(size: tuple[int, int], tmp_path: Path):
    workspace = tmp_path.joinpath(*["nested"] * DEPTH, "gauntlet-work")
    runner = FakeJobRunner(machine=fake_machine(workspace=str(workspace)))
    app = workbench_app(runner)
    async with app.run_test(size=size) as pilot:
        await opened(app, pilot, "calibrate")
        lines = screen_text(app).splitlines()
        line = next(text for text in lines if "workspace" in text)
        assert f"workspace {str(tmp_path)[:2]}" in line
        assert line.rstrip().endswith("gauntlet-work")
        assert "…" in line


def test_a_short_workspace_path_is_shown_whole():
    look = make_look({})
    line = machine_line(fake_machine(workspace="/tmp/work"), look, width=200).plain
    assert line.endswith("workspace /tmp/work")


async def test_a_finished_jobs_toast_opens_it_on_the_workbench(monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()
    app = workbench_app(runner)
    toasts: list[str] = []
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        monkeypatch.setattr(app, "notify", lambda message, **_kw: toasts.append(message))
        record = runner.submit(make_spec(title="Odd [red]title[/red]"))
        runner.run_until_idle()
        await settle(app, pilot)
        assert toasts == [f"Odd \\[red]title\\[/red] succeeded. [@click=app.open_job('{record.id}')]Open it[/]"]
        await app.run_action(f"app.open_job('{record.id}')")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen) and app.screen.job_id == record.id
        assert app.current_mode == "workbench"
        await app.run_action(f"app.open_job('{record.id}')")
        await settle(app, pilot)
        assert len(app.screen_stack) == 2
