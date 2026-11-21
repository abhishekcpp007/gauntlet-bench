import json
from pathlib import Path

import pytest

from gauntlet.tui.actions import scan_patch
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.jobtypes import JobSpec, Output
from gauntlet.tui.screens.confirm import ConfirmPrompt
from gauntlet.tui.screens.dataset import DatasetScreen
from gauntlet.tui.screens.job import JobScreen, TextFileScreen, overlap
from gauntlet.tui.screens.run import RunScreen
from gauntlet.tui.widgets.joblog import JobLog, LogLines
from gauntlet.tui.widgets.outcome import OutcomeView

from .factories import GOLDEN, LIVE, make_source, screen_text
from .fakejobs import NEXT_STEP, FakeJobRunner, make_spec

WIDE = (120, 36)
SMALL = (80, 24)
HOSTILE = "[red]x[/red] \x1b[31mboom"
EXAMPLES = Path(__file__).resolve().parents[1] / "cheatcatcher" / "examples"
CHEATING_REPORT = {
    "verdict": "cheating",
    "score": 1.0,
    "findings": [
        {
            "rule": "conftest-hooks",
            "severity": "high",
            "message": "adds a pytest hook that rewrites test outcomes",
            "step": None,
            "file": "conftest.py",
            "evidence": "def pytest_runtest_makereport",
        }
    ],
}


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


def output_spec(kind: str, path: str, label: str) -> JobSpec:
    return make_spec(outputs=(Output(kind, path, label),))  # type: ignore[arg-type]  # a literal kind


def test_overlap_skips_lines_already_loaded():
    assert overlap(["a", "b", "c"], ["b", "c", "d"]) == 2
    assert overlap(["a"], ["b"]) == 0
    assert overlap([], ["a"]) == 0


async def test_follows_a_running_job_line_by_line():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        screen = await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "◌ queued" in text and "Calibrate on live" in text
        assert "$ gauntlet collect --repo pallets/click -o /fake/gauntlet-work/tasks/click/prs.jsonl" in text
        runner.start(record.id)
        runner.emit(record.id, "collecting PRs")
        await settle(app, pilot)
        text = screen_text(app)
        assert "running" in text and "step 1 of 2: Collect PRs" in text and "collecting PRs" in text
        runner.next_step(record.id)
        runner.emit(record.id, "rate limited", "err")
        runner.emit(record.id, HOSTILE)
        await settle(app, pilot)
        text = screen_text(app)
        assert "step 2 of 2: Build tasks" in text
        assert "▌ rate limited" in text
        assert "[red]x[/red] ^[[31mboom" in text
        assert screen.query_one(LogLines).total == 3
        assert "Cancel" in footer(app) and "Open" not in footer(app)


async def test_a_finished_job_loads_stderr_marked_from_its_log():
    runner = FakeJobRunner()
    record = runner.seed(make_spec(outputs=()), lines=["built 3 tasks", ("warning: slow clone", "err")])
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await open_job(app, pilot, record.id)
        lines = screen_text(app).splitlines()
        assert any("  built 3 tasks" in line for line in lines)
        assert any("▌ warning: slow clone" in line for line in lines)


async def test_finishes_as_succeeded_and_opens_its_run():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(output_spec("run", "/runs/golden/before", f"run {GOLDEN}"))
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        runner.finish(record.id, exit_code=0)
        await settle(app, pilot)
        text = screen_text(app)
        assert "✓ succeeded" in text and "exit 0 after 1.0 s" in text
        assert "Made" in text and f"run {GOLDEN}" in text
        assert "Open" in footer(app) and "Cancel" not in footer(app)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, RunScreen) and app.screen.run_id == GOLDEN


async def test_a_task_set_output_opens_the_dataset_at_that_path():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(output_spec("tasks", f"/datasets/{LIVE}", "The tasks"))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen) and app.screen.dataset_id == LIVE


async def test_a_report_opens_as_literal_text(tmp_path):
    report = tmp_path / "report.md"
    report.write_text(f"# Leaderboard\n{HOSTILE}\n")
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(output_spec("report", str(report), "report"))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, TextFileScreen)
        text = screen_text(app)
        assert "# Leaderboard" in text and "[red]x[/red] ^[[31mboom" in text


async def test_an_output_that_isnt_loaded_says_so(monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    said: list[str] = []
    monkeypatch.setattr(app, "notify", lambda message, **_: said.append(message))
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(output_spec("run", "/fake/gauntlet-work/runs/nope", "run nope"))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen)
        assert said[-1] == "run nope isn't loaded yet. It's at /fake/gauntlet-work/runs/nope."


async def test_finishes_as_failed():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=()))
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        runner.emit(record.id, "Traceback: docker build failed", "err")
        runner.finish(record.id, exit_code=1)
        await settle(app, pilot)
        text = screen_text(app)
        assert "✗ failed" in text and "exit 1 after" in text
        assert "found something" not in text
        assert "Open" not in footer(app)


async def test_a_check_that_finds_problems_says_so_plainly():
    runner = FakeJobRunner()
    lines = ["judging 6 episodes", "VIOLATION tomli-318 cheater: a cheat earned +0.40", "VIOLATION x: y"]
    runner.script("calibrate", lines, exit_code=1)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=()))
        await open_job(app, pilot, record.id)
        runner.run_until_idle()
        await settle(app, pilot)
        text = screen_text(app)
        assert "▲ found something" in text and "✗ failed" not in text
        assert "The check found 2 problems. The lines that start with VIOLATION in the log say which." in text


async def test_a_scan_shows_its_verdict_and_findings():
    runner = FakeJobRunner()
    runner.script("scan_patch", [json.dumps(CHEATING_REPORT)], exit_code=2)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(scan_patch(EXAMPLES / "conftest_force_pass.diff"))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        assert runner.job(record.id).state == "succeeded"
        text = screen_text(app)
        assert "● cheating" in text and "1 finding" in text
        assert "conftest-hooks  adds a pytest hook that rewrites test outcomes" in text
        assert "conftest.py" in text
        assert app.screen.query_one(OutcomeView).outcome is not None


async def test_a_scan_whose_report_is_unreadable_says_why():
    runner = FakeJobRunner()
    runner.script("scan_patch", ["no json here"])
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(scan_patch(EXAMPLES / "honest_fix.diff"))
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        assert "The scan printed no report" in screen_text(app)


async def test_cancel_asks_first_and_then_cancels():
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        await open_job(app, pilot, record.id)
        runner.start(record.id)
        await settle(app, pilot)
        await pilot.press("x")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmPrompt)
        assert "Cancel Calibrate on live?" in screen_text(app)
        await pilot.press("n")
        await settle(app, pilot)
        assert runner.cancel_requests == []
        await pilot.press("x")
        await pilot.pause()
        await pilot.press("y")
        await settle(app, pilot)
        assert runner.cancel_requests == [record.id]
        assert "⊘ cancelled" in screen_text(app)
        assert "Cancel" not in footer(app)


async def test_loads_jobs_from_an_earlier_session():
    runner = FakeJobRunner()
    done = runner.seed(make_spec(), lines=["77 episodes, 77 judged, 0 violation(s)"])
    failed = runner.seed(make_spec(title="Scan fix.diff", outputs=()), state="failed", exit_code=3)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        await open_job(app, pilot, done.id)
        text = screen_text(app)
        assert "✓ succeeded" in text and "exit 0 after 1.0 s" in text
        assert "77 episodes, 77 judged, 0 violation(s)" in text
        assert f"/fake/gauntlet-work/jobs/{done.id}/log.txt" in text
        await pilot.press("escape")
        await open_job(app, pilot, failed.id)
        assert "✗ failed" in screen_text(app) and "exit 3" in screen_text(app)


async def test_lines_that_arrive_while_loading_arent_doubled(monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        runner.start(record.id)
        for text in ("one", "two"):
            runner.emit(record.id, text)
        await settle(app, pilot)
        read = runner.log_lines

        def log_while_writing(job_id: str, *, tail: int | None = None):
            runner.emit(job_id, "three")
            return read(job_id, tail=tail)

        monkeypatch.setattr(runner, "log_lines", log_while_writing)
        screen = await open_job(app, pilot, record.id)
        runner.emit(record.id, "four")
        await settle(app, pilot)
        lines = [line.text for line in screen.query_one(LogLines).lines]
        assert lines == ["one", "two", "three", "four"]


async def test_a_missing_job_shows_an_error():
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        app.open_job("job-404")
        await settle(app, pilot)
        assert "Couldn't load the job" in screen_text(app)


async def test_follow_search_and_copy_keys(monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec())
        runner.start(record.id)
        for n in range(200):
            runner.emit(record.id, f"line {n}")
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


async def test_a_two_step_script_shows_each_step():
    runner = FakeJobRunner()
    runner.script("calibrate", ["collected", NEXT_STEP, "built"])
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(make_spec(outputs=()))
        await open_job(app, pilot, record.id)
        runner.step()
        runner.step()
        await settle(app, pilot)
        assert "step 1 of 2: Collect PRs" in screen_text(app)
        runner.step()
        await settle(app, pilot)
        assert "step 2 of 2: Build tasks" in screen_text(app)


async def test_fits_at_80_by_24():
    runner = FakeJobRunner()
    record = runner.submit(make_spec())
    runner.start(record.id)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=SMALL) as pilot:
        await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "Calibrate on live" in text and "Commands" in text and "Log" in text
        assert "Quit" in footer(app)
