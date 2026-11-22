import pytest

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.jobtypes import JobSpec
from gauntlet.tui.screens.dataset import DatasetScreen
from gauntlet.tui.screens.episode import EpisodeScreen
from gauntlet.tui.screens.help import HelpScreen, per_row
from gauntlet.tui.screens.run import RunScreen
from gauntlet.tui.screens.runs import RunsScreen
from gauntlet.tui.screens.task import TaskScreen
from gauntlet.tui.screens.tasks import TasksScreen
from gauntlet.tui.screens.workbench import WorkbenchScreen
from gauntlet.tui.widgets.pickers import Picker
from gauntlet.tui.workbench.base import (
    SHORTCUT_KEYS,
    SUMMARY_ONLY_RUN,
    ActionForm,
    Field,
    PathField,
    RunField,
    TaskField,
    TaskSetField,
    TextField,
    Values,
)

from .factories import GOLDEN, LIVE, SHIPPED_LIVE, make_source, screen_text
from .fakejobs import FakeJobRunner, make_spec

WIDE = (140, 40)
SMALL = (80, 24)
TOMLI = "hukkin__tomli-318"
TOMLI_CHEAT = "hukkin__tomli-318__cheater__0"


def form_for(action_id: str, *fields: Field) -> type[ActionForm]:
    def build(self: ActionForm, values: Values) -> JobSpec:
        return make_spec(action=action_id)

    members = {"action_id": action_id, "fields": fields, "build": build}
    return type(f"Form_{action_id}", (ActionForm,), members)


def task_set() -> TaskSetField:
    return TaskSetField(name="tasks", label="Task set")


FORMS: dict[str, type[ActionForm]] = {
    "make_tasks": form_for("make_tasks", TextField(name="repos", label="Repos")),
    "leakcheck": form_for("leakcheck", task_set()),
    "check_envs": form_for("check_envs", task_set()),
    "calibrate": form_for("calibrate", task_set()),
    "run_policies": form_for("run_policies", task_set()),
    "try_patch": form_for(
        "try_patch",
        task_set(),
        TaskField(name="task", label="Task", task_set="tasks"),
        PathField(name="patch", label="Patch file"),
    ),
    "report": form_for("report", RunField(name="run", label="Run", results=True)),
}
ALL_KEYS = tuple(SHORTCUT_KEYS.values())


def make_app(*, runner: bool = True) -> GauntletApp:
    return GauntletApp(make_source(), jobs=FakeJobRunner() if runner else None, forms=FORMS)


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)
    await app.workers.wait_for_complete()
    await pilot.pause()


def footer(app: GauntletApp) -> str:
    return screen_text(app).splitlines()[-1]


def value(screen: WorkbenchScreen, action_id: str, name: str) -> str | None:
    control = screen.forms[action_id].row(name).control
    assert isinstance(control, Picker)
    return control.value


async def press(app: GauntletApp, pilot, key: str) -> WorkbenchScreen:
    await pilot.press(key)
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, WorkbenchScreen)
    return screen


async def on_task(app: GauntletApp, pilot) -> None:
    await settle(app, pilot)
    app.open_task(TOMLI)
    await settle(app, pilot)
    assert isinstance(app.screen, TaskScreen)


async def test_each_idea_has_its_own_key_and_no_key_is_taken():
    assert len(set(ALL_KEYS)) == len(ALL_KEYS)
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        opens = (
            lambda: app.open_task(TOMLI),
            lambda: app.open_dataset(LIVE),
            lambda: app.open_run(GOLDEN),
            lambda: app.open_episode(GOLDEN, TOMLI_CHEAT),
        )
        for open_screen in opens:
            open_screen()
            await settle(app, pilot)
            for key in ALL_KEYS:
                bound = app.screen.active_bindings.get(key)
                assert bound is None or bound.binding.action.startswith("app.workbench(")


async def test_task_screen_tries_a_patch_on_this_task():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await on_task(app, pilot)
        assert "Try a patch" in footer(app) and "Leak check" in footer(app)
        screen = await press(app, pilot, SHORTCUT_KEYS["try_patch"])
        assert screen.current == "try_patch"
        assert value(screen, "try_patch", "tasks") == LIVE
        assert value(screen, "try_patch", "task") == TOMLI
        assert app.focused in screen.forms["try_patch"].row("patch").query("*")


async def test_task_screen_leak_checks_its_task_set():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await on_task(app, pilot)
        screen = await press(app, pilot, SHORTCUT_KEYS["leakcheck"])
        assert screen.current == "leakcheck"
        assert value(screen, "leakcheck", "tasks") == LIVE


@pytest.mark.parametrize("action_id", ["calibrate", "run_policies", "leakcheck", "check_envs"])
async def test_dataset_screen_opens_each_check_on_this_set(action_id: str):
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_dataset(LIVE)
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen)
        for words in ("Calibrate", "Run policies", "Leak check", "Fingerprints"):
            assert words in footer(app)
        screen = await press(app, pilot, SHORTCUT_KEYS[action_id])
        assert screen.current == action_id
        assert value(screen, action_id, "tasks") == LIVE


async def test_tasks_screen_makes_tasks():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("2")
        await settle(app, pilot)
        assert isinstance(app.screen, TasksScreen)
        assert "Make tasks" in footer(app)
        screen = await press(app, pilot, SHORTCUT_KEYS["make_tasks"])
        assert screen.current == "make_tasks"
        assert app.focused in screen.forms["make_tasks"].row("repos").query("*")


async def test_run_screen_reports_on_this_run():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_run(GOLDEN)
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen)
        assert "Report" in footer(app)
        screen = await press(app, pilot, SHORTCUT_KEYS["report"])
        assert screen.current == "report"
        assert value(screen, "report", "run") == GOLDEN


async def test_runs_screen_reports_on_the_highlighted_run():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("3")
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        screen = await press(app, pilot, SHORTCUT_KEYS["report"])
        assert value(screen, "report", "run") == GOLDEN


async def test_a_summary_only_run_says_it_cant_be_reported_on(monkeypatch: pytest.MonkeyPatch):
    app = make_app()
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_kw: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("3")
        await settle(app, pilot)
        await pilot.press("j")
        assert app.screen.query_one("#runs").current_key == SHIPPED_LIVE
        await pilot.press(SHORTCUT_KEYS["report"])
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        app.open_run(SHIPPED_LIVE)
        await settle(app, pilot)
        await pilot.press(SHORTCUT_KEYS["report"])
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen)
        assert said == [SUMMARY_ONLY_RUN, SUMMARY_ONLY_RUN]


async def test_episode_screen_tries_another_patch_on_its_task():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_episode(GOLDEN, TOMLI_CHEAT)
        await settle(app, pilot)
        assert isinstance(app.screen, EpisodeScreen)
        assert "Try a patch" in footer(app)
        screen = await press(app, pilot, SHORTCUT_KEYS["try_patch"])
        assert value(screen, "try_patch", "task") == TOMLI
        assert value(screen, "try_patch", "tasks") == LIVE


async def test_back_from_the_workbench_keeps_the_viewer_where_it_was():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await on_task(app, pilot)
        await press(app, pilot, SHORTCUT_KEYS["leakcheck"])
        await pilot.press("1")
        await settle(app, pilot)
        assert isinstance(app.screen, TaskScreen)


async def test_without_a_runner_the_viewer_has_no_workbench_keys():
    app = make_app(runner=False)
    async with app.run_test(size=WIDE) as pilot:
        await on_task(app, pilot)
        for key in ALL_KEYS:
            await pilot.press(key)
            await settle(app, pilot)
            assert isinstance(app.screen, TaskScreen)
        assert "Try a patch" not in footer(app)
        app.open_dataset(LIVE)
        await settle(app, pilot)
        assert "Calibrate" not in footer(app) and "Fingerprints" not in footer(app)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        assert "Workbench" not in [name for name, _ in app.screen.groups]


async def test_help_lists_the_workbench_keys_on_a_viewer_screen():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_dataset(LIVE)
        await settle(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        groups = dict(app.screen.groups)
        described = {k.description for k in groups["Workbench"]}
        assert described == {"Calibrate", "Run policies", "Leak check", "Fingerprints"}


async def test_the_overview_points_to_the_workbench_only_with_a_runner():
    for runner, shown in ((True, True), (False, False)):
        app = make_app(runner=runner)
        async with app.run_test(size=WIDE) as pilot:
            await settle(app, pilot)
            assert ("Press 5 for the Workbench" in screen_text(app)) is shown


@pytest.mark.parametrize("size", [WIDE, SMALL])
async def test_the_footer_still_ends_with_quit(size: tuple[int, int]):
    app = make_app()
    async with app.run_test(size=size) as pilot:
        await on_task(app, pilot)
        assert "Quit" in footer(app) or "Help" in footer(app)


async def test_help_on_the_workbench_lists_every_pane_under_its_name():
    app = make_app()
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("5")
        await settle(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        groups = {name: {k.description for k in keys} for name, keys in app.screen.groups}
        assert "Fill in" in groups["Actions"]
        assert {"Review", "Choose"} <= groups["Form"]
        assert "Recheck machine" in groups["Workbench"]
        assert list(groups)[-1] == "Everywhere"


def test_help_puts_fewer_groups_side_by_side_on_a_narrow_terminal():
    wide, narrow, tiny = (per_row(width, len(ALL_KEYS)) for width in (WIDE[0], SMALL[0], len(ALL_KEYS)))
    assert wide > narrow > tiny == 1
    assert per_row(WIDE[0], 1) == 1
