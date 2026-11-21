import pytest

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.jobtypes import Output
from gauntlet.tui.screens.confirm import ConfirmPrompt
from gauntlet.tui.screens.dataset import DatasetScreen
from gauntlet.tui.screens.job import JobScreen, TextFileScreen, overlap
from gauntlet.tui.screens.run import RunScreen
from gauntlet.tui.widgets.joblog import JobLog, LogLines

from .factories import GOLDEN, LIVE, make_source, screen_text
from .workfakes import ScriptedRunner, finished_runner, make_record, make_spec

WIDE = (120, 36)
SMALL = (80, 24)
HOSTILE = "[red]x[/red] \x1b[31mboom"


async def settle(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


async def open_job(app: GauntletApp, pilot, job_id: str) -> JobScreen:
    await settle(app, pilot)
    app.open_job(job_id)
    await settle(app, pilot)
    assert isinstance(app.screen, JobScreen)
    return app.screen


def footer(app: GauntletApp) -> str:
    return screen_text(app).splitlines()[-1]


def test_overlap_skips_lines_already_loaded():
    assert overlap(["a", "b", "c"], ["b", "c", "d"]) == 2
    assert overlap(["a"], ["b"]) == 0
    assert overlap([], ["a"]) == 0


async def test_follows_a_running_job_line_by_line():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        screen = await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "◌ queued" in text and "Calibrate live" in text
        assert "$ gauntlet collect --repo pallets/click -o gauntlet-work/tasks/click/prs.jsonl" in text
        assert "$ gauntlet build --prs gauntlet-work/tasks/click/prs.jsonl" in text
        runner.start(record.id)
        runner.line(record.id, "collecting PRs")
        await settle(app, pilot)
        text = screen_text(app)
        assert "running" in text and "step 1 of 2: collect" in text and "collecting PRs" in text
        runner.step(record.id, 1)
        runner.line(record.id, "rate limited", "err")
        runner.line(record.id, HOSTILE)
        await settle(app, pilot)
        text = screen_text(app)
        assert "step 2 of 2: build" in text
        assert "▌ rate limited" in text
        assert "[red]x[/red] ^[[31mboom" in text
        assert screen.query_one(LogLines).total == 3
        assert "Cancel" in footer(app) and "Open" not in footer(app)


async def test_finishes_as_succeeded_and_opens_its_run():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        spec = make_spec(outputs=(Output("run", f"gauntlet-work/runs/{GOLDEN}", f"run {GOLDEN}"),))
        record = runner.submit(spec)
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        runner.finish(record.id, exit_code=0)
        await settle(app, pilot)
        text = screen_text(app)
        assert "✓ succeeded" in text and "exit 0 after 3.0 s" in text
        assert "Made" in text and f"run {GOLDEN}" in text
        assert "Open" in footer(app) and "Cancel" not in footer(app)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen) and app.screen.run_id == GOLDEN


async def test_a_task_set_output_opens_the_dataset():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        spec = make_spec(outputs=(Output("tasks", f"gauntlet-work/tasks/{LIVE}/tasks.jsonl", "task set"),))
        record = runner.submit(spec)
        runner.start(record.id)
        runner.finish(record.id)
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen)


async def test_a_report_opens_as_literal_text(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(f"# Leaderboard\n{HOSTILE}\n")
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=(Output("report", str(report), "report"),)))
        runner.finish(record.id)
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, TextFileScreen)
        text = screen_text(app)
        assert "# Leaderboard" in text and "[red]x[/red] ^[[31mboom" in text


async def test_an_output_that_isnt_loaded_says_so(monkeypatch: pytest.MonkeyPatch):
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=(Output("run", "gauntlet-work/runs/nope", "run nope"),)))
        runner.finish(record.id)
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen)
        assert said[-1] == "run nope isn't loaded yet. It's at gauntlet-work/runs/nope."


async def test_finishes_as_failed():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=()))
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        runner.line(record.id, "Traceback: docker build failed", "err")
        runner.finish(record.id, exit_code=1)
        await settle(app, pilot)
        text = screen_text(app)
        assert "✗ failed" in text and "exit 1 after 3.0 s" in text
        assert "Open" not in footer(app)


async def test_cancel_asks_first_and_then_cancels():
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        await settle(app, pilot)
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmPrompt)
        assert "Cancel Calibrate live?" in screen_text(app)
        await pilot.press("n")
        await settle(app, pilot)
        assert runner.cancelled == []
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)
        assert runner.cancelled == [record.id]
        assert "⊘ cancelled" in screen_text(app)
        assert "Cancel" not in footer(app)


async def test_loads_a_job_from_an_earlier_session():
    app = GauntletApp(make_source(), jobs=finished_runner())
    async with app.run_test(size=WIDE) as pilot:
        await open_job(app, pilot, "job-1")
        text = screen_text(app)
        assert "✓ succeeded" in text and "exit 0 after 1 m 05 s" in text
        assert "77 episodes, 77 judged, 0 violation(s)" in text
        assert "gauntlet-work/jobs/job-1/log.txt" in text
        await pilot.press("escape")
        await open_job(app, pilot, "job-2")
        assert "✗ failed" in screen_text(app) and "exit 2" in screen_text(app)


async def test_lines_that_arrive_while_loading_arent_doubled(monkeypatch: pytest.MonkeyPatch):
    runner = ScriptedRunner(threaded=True)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        runner.start(record.id)
        runner.lines(record.id, ["one", "two"])
        await settle(app, pilot)
        read = runner.log

        def log_while_writing(job_id: str, *, tail: int | None = None) -> tuple[str, ...]:
            runner.line(job_id, "three")
            return read(job_id, tail=tail)

        monkeypatch.setattr(runner, "log", log_while_writing)
        screen = await open_job(app, pilot, record.id)
        runner.line(record.id, "four")
        await settle(app, pilot)
        lines = [line.text for line in screen.query_one(LogLines).lines]
        assert lines == ["one", "two", "three", "four"]


async def test_a_missing_job_shows_an_error():
    app = GauntletApp(make_source(), jobs=ScriptedRunner())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_job("job-404")
        await settle(app, pilot)
        assert "Couldn't load the job" in screen_text(app)


async def test_follow_search_and_copy_keys(monkeypatch: pytest.MonkeyPatch):
    runner = ScriptedRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        runner.start(record.id)
        runner.lines(record.id, [f"line {n}" for n in range(200)])
        screen = await open_job(app, pilot, record.id)
        log = screen.query_one(JobLog)
        assert log.follow and "following" in screen_text(app)
        await pilot.press("f")
        await pilot.pause()
        assert not log.follow and "paused" in screen_text(app)
        await pilot.press("slash", *"line 7", "enter")
        await pilot.pause()
        assert log.lines.match == 7
        copied: list[tuple[str, str]] = []
        monkeypatch.setattr(app, "copy", lambda text, what="id": copied.append((text, what)))
        await pilot.press("c")
        assert copied and copied[0][1] == "commands"
        assert copied[0][0].splitlines()[0].startswith("gauntlet collect --repo pallets/click")


async def test_fits_at_80_by_24():
    runner = finished_runner()
    runner.records["job-1"] = make_record("job-1", state="running", started_at=1.0)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=SMALL) as pilot:
        await open_job(app, pilot, "job-1")
        text = screen_text(app)
        assert "Calibrate live" in text and "Commands" in text and "Log" in text
        assert "Quit" in footer(app)
