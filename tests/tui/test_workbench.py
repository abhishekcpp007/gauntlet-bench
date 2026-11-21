from dataclasses import replace

import pytest

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob, ConfirmPrompt
from gauntlet.tui.screens.help import HelpScreen
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.runs import RunsScreen
from gauntlet.tui.screens.workbench import ActionList, WorkbenchScreen, machine_line
from gauntlet.tui.theme import make_look
from gauntlet.tui.widgets.form import FormView
from gauntlet.tui.widgets.grid import DataGrid
from gauntlet.tui.widgets.pickers import PickList

from .factories import GOLDEN, LIVE, SHIPPED_LIVE, make_run_summary, make_source, screen_text
from .workfakes import ScriptedRunner, fill, finished_runner, make_machine, make_spec

WIDE = (140, 40)
SMALL = (80, 24)


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


def top_line(app: GauntletApp) -> str:
    return screen_text(app).splitlines()[0]


async def test_the_workbench_only_shows_with_a_runner():
    viewer = GauntletApp(make_source())
    async with viewer.run_test(size=WIDE) as pilot:
        await settle(viewer, pilot)
        assert "5 Workbench" not in screen_text(viewer)
        await pilot.press("5")
        assert not isinstance(viewer.screen, WorkbenchScreen)
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert "5 Workbench" in screen_text(app)
        await open_workbench(app, pilot)
        assert top_line(app).startswith(" GAUNTLET  Workbench")


async def test_the_machine_line_says_what_this_machine_can_do():
    runner = ScriptedRunner(make_machine(anthropic_key_set=True))
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        line = screen_text(app).splitlines()[3]
        assert "✓ Docker running" in line and "42.0 GB free" in line
        assert "✓ Anthropic key set" in line and "workspace gauntlet-work" in line


def test_the_machine_line_names_whats_missing_and_never_a_key():
    look = make_look({})
    machine = make_machine(docker_running=False, docker_detail="Cannot connect", free_disk_bytes=1024**3)
    line = machine_line(machine, look).plain
    assert "Docker isn't running (Cannot connect)" in line
    assert "▲ 1.0 GB free" in line and "no Anthropic key" in line
    assert "Couldn't check the machine" in machine_line(None, look, "boom").plain
    assert "Checking the machine" in machine_line(None, look).plain


async def test_actions_are_grouped_and_the_focused_one_described():
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        actions = app.screen.query_one(ActionList)
        prompts = [str(actions.get_option_at_index(i).prompt).strip() for i in range(actions.option_count)]
        assert prompts == ["Check", "Calibrate", "Score", "Scan a patch"]
        text = screen_text(app)
        assert "Red-team the grader" in text and "Needs  Docker" in text
        await pilot.press("j")
        await pilot.pause()
        text = screen_text(app)
        assert "Check a diff for cheating" in text and "Needs  nothing but this machine" in text
        assert app.screen.query_one("#form-pane").border_title == "Scan a patch"


async def test_an_unmet_need_blocks_starting_and_says_why():
    runner = ScriptedRunner(
        make_machine(docker_running=False, docker_detail="Cannot connect to the Docker daemon")
    )
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        text = screen_text(app)
        assert "needs Docker" in text
        assert "Can't start" in text and "Docker isn't running (Cannot connect to the Docker daemon)" in text
        view = screen.forms["calibrate"]
        fill(view, tasks=LIVE)
        assert view.review() is None
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmJob)
        assert runner.submitted == []


async def test_the_confirm_step_shows_the_commands_and_starts_the_job():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pilot.press("enter", "enter")
        await settle(app, pilot)
        assert isinstance(app.screen, PickList)
        await pilot.press(*"lht", "enter")
        await pilot.pause()
        assert screen.forms["calibrate"].row("tasks").control.value == "gauntlet-lht-2026-11"
        await pilot.press("ctrl+r")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        text = screen_text(app)
        assert "Start Calibrate gauntlet-lht-2026-11?" in text
        command = "$ gauntlet calibrate --tasks datasets/gauntlet-lht-2026-11/tasks.jsonl --sample 3"
        assert "".join(command.split()) in "".join(text.replace("│", "").split())
        assert "✓ Docker" in text and "Free disk" in text and "this starts now" in text
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen and screen.forms["calibrate"].row("tasks").control.value is not None
        await pilot.press("ctrl+r")
        await pilot.pause()
        await pilot.press("enter")
        await settle(app, pilot)
        assert len(runner.submitted) == 1
        spec = runner.submitted[0]
        assert spec.action == "calibrate" and spec.needs == ("docker",)
        argv = spec.steps[0].argv
        assert argv[:3] == ("calibrate", "--tasks", "datasets/gauntlet-lht-2026-11/tasks.jsonl")
        assert isinstance(app.screen, JobScreen)
        assert "Workbench › Calibrate gauntlet-lht-2026-11" in top_line(app)


async def test_a_docker_job_waits_behind_another():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        runner.start(runner.submit(make_spec()).id)
        await settle(app, pilot)
        fill(screen.forms["calibrate"], tasks=LIVE)
        screen.forms["calibrate"].review()
        await pilot.pause()
        assert "Another Docker job is running, so this one waits its turn" in screen_text(app)


async def test_the_jobs_tab_lists_newest_first_and_opens_one():
    app = GauntletApp(make_source(), jobs=finished_runner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        assert "Jobs 3" in screen_text(app)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        grid = screen.query_one("#job-grid", DataGrid)
        assert [r.id for r in grid.rows] == ["job-3", "job-2", "job-1"]
        text = screen_text(app)
        assert "⊘ cancelled" in text and "✗ failed" in text and "✓ succeeded" in text
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen) and app.screen.job_id == "job-3"


async def test_an_empty_jobs_tab_says_what_to_do():
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        await pilot.press("right_square_bracket")
        await settle(app, pilot)
        assert "No jobs yet." in screen_text(app)


async def test_the_header_counts_running_and_queued_jobs():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        assert top_line(app).rstrip().endswith("12 tasks · 2 runs")
        first, second, third = (runner.submit(make_spec()) for _ in range(3))
        runner.start(first.id)
        runner.start(second.id)
        await settle(app, pilot)
        assert "2 jobs running · 1 queued · 12 tasks · 2 runs" in top_line(app)
        for job in (first, second, third):
            runner.finish(job.id)
        await settle(app, pilot)
        assert "running" not in top_line(app)


async def test_a_toast_says_when_a_job_ends(monkeypatch: pytest.MonkeyPatch):
    runner = ScriptedRunner(threaded=True)
    app = GauntletApp(make_source(), jobs=runner)
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(app, "notify", lambda message, **kw: toasts.append((message, kw.get("severity", ""))))
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        good, bad = runner.submit(make_spec()), runner.submit(make_spec(title="Scan fix.diff"))
        runner.start(good.id)
        runner.finish(good.id)
        runner.finish(bad.id, exit_code=2)
        await settle(app, pilot)
        assert ("Calibrate live succeeded.", "information") in toasts
        assert ("Scan fix.diff failed.", "error") in toasts


async def test_a_finished_job_reloads_an_open_list_and_keeps_your_place():
    fresh = make_source()
    fresh_runs = fresh.runs()

    def reload():
        extra = make_run_summary("calibrate-new", ())
        source = make_source()
        source.runs = lambda: (*fresh_runs, extra)
        return source

    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner, reload=reload)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("3")
        await settle(app, pilot)
        assert isinstance(app.screen, RunsScreen)
        await pilot.press("j")
        assert app.screen.query_one("#runs", DataGrid).current_key == SHIPPED_LIVE
        runner.finish(runner.submit(make_spec()).id)
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
    runner = ScriptedRunner()
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
    runner = finished_runner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        await pilot.press("q")
        await pilot.pause()
    assert runner.closed and not runner.listeners


async def test_help_lists_the_workbench_keys():
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=WIDE) as pilot:
        await open_workbench(app, pilot)
        await pilot.press("question_mark")
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        text = screen_text(app)
        assert "Workbench" in text and "Fill in" in text


async def test_fits_at_80_by_24_with_each_example_form():
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        assert screen.has_class("-narrow")
        assert screen.forms["calibrate"].has_class("-stacked")
        text = screen_text(app)
        assert "Calibrate" in text and "Task set" in text and "Quit" in text.splitlines()[-1]
        await pilot.press("j")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "Patch file" in screen_text(app)
        assert app.focused in screen.forms["scan"].row("patch").query("*")


async def test_a_refused_job_keeps_the_form(monkeypatch: pytest.MonkeyPatch):
    runner = ScriptedRunner()

    def refuse(spec):
        raise RuntimeError("the workspace is full")

    monkeypatch.setattr(runner, "submit", refuse)
    app = GauntletApp(make_source(), jobs=runner)
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
    machine = replace(make_machine(), docker_running=False)
    app = GauntletApp(make_source(), jobs=ScriptedRunner(machine))
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        prompt = screen.query_one(ActionList).get_option("calibrate").prompt
        assert "needs Docker" in str(prompt)
        assert isinstance(screen.forms["scan"], FormView) and screen.forms["scan"].blocked is None
