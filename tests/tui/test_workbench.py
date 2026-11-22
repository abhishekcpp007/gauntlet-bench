from dataclasses import replace
from pathlib import Path

import pytest

from gauntlet.tui.actions import ACTIONS
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob, ConfirmPrompt
from gauntlet.tui.screens.help import HelpScreen
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.runs import RunsScreen
from gauntlet.tui.screens.workbench import ActionList, NoForm, WorkbenchScreen, machine_line
from gauntlet.tui.theme import make_look
from gauntlet.tui.widgets.grid import DataGrid
from gauntlet.tui.widgets.pickers import PickList
from gauntlet.tui.workbench.scan import ScanPatch

from .factories import GOLDEN, LHT, LIVE, SHIPPED_LIVE, FakeSource, make_run_summary, make_source, screen_text
from .fakejobs import FakeJobRunner, fake_machine, fill, make_spec

WIDE = (140, 40)
SMALL = (80, 24)
GIB = 1024**3


def source_with_files(tmp_path: Path) -> FakeSource:
    """The sample data, with every task set's file really there."""
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text("")
    source = make_source()
    shown = tuple(replace(d, tasks_file=str(tasks)) for d in source.datasets())
    source.datasets = lambda: shown  # type: ignore[method-assign]  # a test double
    return source


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


async def open_workbench(app: GauntletApp, pilot) -> WorkbenchScreen:
    await settle(app, pilot)
    await pilot.press("5")
    await settle(app, pilot)
    assert isinstance(app.screen, WorkbenchScreen)
    return app.screen


async def pick(screen: WorkbenchScreen, pilot, action_id: str) -> None:
    actions = screen.query_one(ActionList)
    actions.highlighted = actions.get_option_index(action_id)
    await pilot.pause()


def top_line(app: GauntletApp) -> str:
    return screen_text(app).splitlines()[0]


async def test_the_workbench_only_shows_with_a_runner():
    viewer = GauntletApp(make_source())
    async with viewer.run_test(size=WIDE) as pilot:
        await settle(viewer, pilot)
        assert "5 Workbench" not in screen_text(viewer)
        await pilot.press("5")
        assert not isinstance(viewer.screen, WorkbenchScreen)
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert "5 Workbench" in screen_text(app)
        await open_workbench(app, pilot)
        assert top_line(app).startswith(" GAUNTLET  Workbench")


async def test_the_machine_line_says_what_this_machine_can_do():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        line = screen_text(app).splitlines()[3]
        assert "✓ Docker running" in line and "50.0 GB free" in line
        assert "✓ Anthropic key set" in line and "workspace /fake/gauntlet-work" in line


def test_the_machine_line_names_whats_missing_and_never_a_key():
    look = make_look({})
    machine = fake_machine(
        docker_running=False, docker_detail="Cannot connect", free_disk_bytes=GIB, anthropic_key_set=False
    )
    line = machine_line(machine, look).plain
    assert "Docker isn't running (Cannot connect)" in line
    assert "▲ 1.0 GB free" in line and "no Anthropic key" in line
    assert "Couldn't check the machine" in machine_line(None, look, "boom").plain
    assert "Checking the machine" in machine_line(None, look).plain


async def test_all_nine_engine_actions_are_listed_in_their_groups():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        actions = screen.query_one(ActionList)
        prompts = [str(actions.get_option_at_index(i).prompt).strip() for i in range(actions.option_count)]
        headers = [p for p in prompts if p in ("Make tasks", "Check", "Score")]
        assert headers == ["Make tasks", "Check", "Score"]
        listed = [actions.get_option_at_index(i).id for i in range(actions.option_count)]
        assert [i for i in listed if not i.startswith("group-")] == [info.id for info in ACTIONS]


async def test_an_action_with_no_form_is_listed_but_marked_and_cant_start():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner, forms={"scan_patch": ScanPatch})
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        for info in ACTIONS:
            prompt = screen.query_one(ActionList).get_option(info.id).prompt
            assert ("◌" in str(prompt)) == (info.id != "scan_patch")
        await pick(screen, pilot, "leakcheck")
        text = screen_text(app)
        assert "◌ not available yet" in text and "doesn't have a form in the Workbench yet" in text
        assert "leak checks again" in text
        assert isinstance(screen.query_one("#forms").visible_content, NoForm)
        assert "leakcheck" not in screen.forms
        await pilot.press("enter", "ctrl+r")
        await pilot.pause()
        assert app.screen is screen and runner.submitted == []


async def test_the_focused_action_is_described_from_the_engine():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "scan_patch")
        info = next(i for i in ACTIONS if i.id == "scan_patch")
        assert info.description[: len("Runs Cheat Catcher's rules")] in screen_text(app)
        assert "Needs  nothing but this machine" in screen_text(app)
        assert screen.query_one("#form-pane").border_title == "Scan a patch"
        await pick(screen, pilot, "calibrate")
        assert "Needs  Docker · network" in screen_text(app)


async def test_an_unmet_need_blocks_starting_and_says_why():
    machine = fake_machine(docker_running=False, docker_detail="Cannot connect to the Docker daemon")
    runner = FakeJobRunner(machine=machine)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "calibrate")
        text = screen_text(app)
        assert "needs Docker" in text
        assert "Can't start" in text and "Docker isn't running (Cannot connect to the Docker daemon)" in text
        view = screen.forms["calibrate"]
        fill(view, tasks=LIVE)
        assert view.review() is None
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmJob)
        assert runner.submitted == []


async def test_a_need_only_the_built_job_has_still_blocks_it(monkeypatch, tmp_path):
    runner = FakeJobRunner(machine=fake_machine(anthropic_key_set=False))
    app = GauntletApp(source_with_files(tmp_path), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "calibrate")
        view = screen.forms["calibrate"]
        built = view.form.build
        monkeypatch.setattr(view.form, "build", lambda values: replace(built(values), needs=("api_key",)))
        fill(view, tasks=LIVE)
        view.review()
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmJob)
        assert "ANTHROPIC_API_KEY isn't set" in screen_text(app)


async def test_the_confirm_step_shows_the_commands_and_starts_the_job(tmp_path):
    runner = FakeJobRunner()
    app = GauntletApp(source_with_files(tmp_path), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "calibrate")
        await pilot.press("enter", "enter")
        await settle(app, pilot)
        assert isinstance(app.screen, PickList)
        await pilot.press(*"lht", "enter")
        await pilot.pause()
        assert screen.forms["calibrate"].row("tasks").control.value == LHT
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        text = screen_text(app)
        assert "Start Calibrate on " in text
        command = f"$ gauntlet calibrate --tasks {(tmp_path / 'tasks.jsonl').resolve()} --sample 3"
        assert "".join(command.split()) in "".join(text.replace("│", "").split())
        assert "✓ Docker" in text and "Free disk" in text and "this starts now" in text
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen and screen.forms["calibrate"].row("tasks").control.value == LHT
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert len(runner.submitted) == 1
        spec = runner.submitted[0]
        assert spec.action == "calibrate" and "docker" in spec.needs
        assert isinstance(app.screen, JobScreen)
        assert "Workbench › Calibrate on " in top_line(app)


async def test_a_docker_job_waits_behind_another(tmp_path):
    runner = FakeJobRunner()
    app = GauntletApp(source_with_files(tmp_path), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        runner.start(runner.submit(make_spec()).id)
        await settle(app, pilot)
        fill(screen.forms["calibrate"], tasks=LIVE)
        screen.forms["calibrate"].review()
        await pilot.pause()
        assert "Another Docker job is running, so this one waits its turn" in screen_text(app)


async def test_the_jobs_tab_lists_newest_first_and_opens_one():
    runner = FakeJobRunner()
    first = runner.seed(make_spec())
    second = runner.seed(make_spec(title="Scan fix.diff"), state="failed", exit_code=3)
    third = runner.seed(make_spec(), state="cancelled")
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        assert "Jobs 3" in screen_text(app)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        grid = screen.query_one("#job-grid", DataGrid)
        assert [r.id for r in grid.rows] == [third.id, second.id, first.id]
        text = screen_text(app)
        assert "⊘ cancelled" in text and "✗ failed" in text and "✓ succeeded" in text
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen) and app.screen.job_id == third.id


async def test_an_empty_jobs_tab_says_what_to_do():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert "No jobs yet." in screen_text(app)


async def test_the_header_counts_running_and_queued_jobs():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert top_line(app).rstrip().endswith("12 tasks · 2 runs")
        first, second, _third = (runner.submit(make_spec()) for _ in range(3))
        runner.start(first.id)
        runner.start(second.id)
        await settle(app, pilot)
        assert "2 jobs running · 1 queued · 12 tasks · 2 runs" in top_line(app)
        runner.run_until_idle()
        await settle(app, pilot)
        assert "running" not in top_line(app)


async def test_a_toast_says_when_a_job_ends(monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()
    runner.script("scan_patch", exit_code=3)
    app = GauntletApp(make_source(), jobs=runner)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: toasts.append((message, kw.get("severity", ""))))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        runner.submit(make_spec())
        runner.submit(make_spec(title="Scan fix.diff", action="scan_patch"))
        runner.run_until_idle()
        await settle(app, pilot)
        said = [(message.split(" [")[0], severity) for message, severity in toasts]
        assert ("Calibrate on live succeeded.", "information") in said
        assert ("Scan fix.diff failed.", "error") in said


async def test_a_finished_job_reloads_an_open_list_and_keeps_your_place():
    fresh_runs = make_source().runs()

    def reload():
        source = make_source()
        extra = make_run_summary("calibrate-new", ())
        source.runs = lambda: (*fresh_runs, extra)  # type: ignore[method-assign]  # a test double
        return source

    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner, reload=reload)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("3")
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        await pilot.press("j")
        assert app.screen.query_one("#runs", DataGrid).current_key == SHIPPED_LIVE
        runner.submit(make_spec())
        runner.run_until_idle()
        await settle(app, pilot)
        await settle(app, pilot)
        grid = app.screen.query_one("#runs", DataGrid)
        assert [r.id for r in grid.rows] == [GOLDEN, SHIPPED_LIVE, "calibrate-new"]
        assert grid.current_key == SHIPPED_LIVE
        await pilot.press("1")
        await settle(app, pilot)
        await settle(app, pilot)
        assert "calibrate-new" in screen_text(app)


async def test_quitting_with_a_job_running_asks_first():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        runner.start(runner.submit(make_spec()).id)
        await settle(app, pilot)
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmPrompt)
        assert "1 job still running or queued. Quit anyway?" in screen_text(app)
        await pilot.press("n")
        await pilot.pause()
        assert app.is_running and not isinstance(app.screen, ConfirmPrompt)
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert runner.closed


async def test_quitting_with_nothing_running_just_quits_and_closes_the_runner():
    runner = FakeJobRunner()
    runner.seed(make_spec())
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("q")
        await pilot.pause()
    assert runner.closed


async def test_help_lists_the_workbench_keys():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        text = screen_text(app)
        assert "Workbench" in text and "Fill in" in text


async def test_fits_at_80_by_24_with_each_example_form():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        assert screen.has_class("-narrow")
        await pick(screen, pilot, "calibrate")
        await settle(app, pilot)
        assert screen.forms["calibrate"].has_class("-stacked")
        text = screen_text(app)
        assert "Calibrate" in text and "Task set" in text and "Quit" in text.splitlines()[-1]
        await pick(screen, pilot, "scan_patch")
        await pilot.press("enter")
        await pilot.pause()
        assert "Patch file" in screen_text(app)
        assert app.focused in screen.forms["scan_patch"].row("patch").query("*")


async def test_a_refused_job_keeps_the_form(monkeypatch: pytest.MonkeyPatch, tmp_path):
    runner = FakeJobRunner()

    def refuse(spec):
        raise RuntimeError("the workspace is full")

    monkeypatch.setattr(runner, "submit", refuse)
    app = GauntletApp(source_with_files(tmp_path), jobs=runner)
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        fill(screen.forms["calibrate"], tasks=LIVE)
        screen.forms["calibrate"].review()
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is screen
        assert said == ["Couldn't start the job: RuntimeError: the workspace is full"]


async def test_the_list_marks_a_blocked_action():
    app = GauntletApp(make_source(), jobs=FakeJobRunner(machine=fake_machine(docker_running=False)))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        prompt = screen.query_one(ActionList).get_option("calibrate").prompt
        assert "needs Docker" in str(prompt) and "network" not in str(prompt)
        assert screen.forms["scan_patch"].blocked is None
