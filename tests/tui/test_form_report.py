from pathlib import Path

import pytest

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.widgets.form import NO_WORKSPACE, FormView
from gauntlet.tui.widgets.jobstatus import command_line
from gauntlet.tui.widgets.reportview import ReportOutcome, ReportScreen, ReportView
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.report import Report
from gauntlet.tui.workspace import Workspace

from .factories import screen_text
from .fakejobs import FakeJobRunner, fill, form_app, row_errors
from .sample import RUN_ID, SAMPLE_RUN, SHIPPED_LIVE, sample_store
from .test_job_screen import open_job
from .test_reportview import real_report
from .test_workbench import open_workbench, pick, settle

WIDE = (140, 40)
SMALL = (80, 24)
NAME = "leaderboard"
RESULTS = SAMPLE_RUN / "results.jsonl"


def flat(text: str) -> str:
    return "".join(text.replace("│", "").split())


async def mounted(app, pilot) -> FormView:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app.query_one(FormView)


def test_it_is_found():
    assert forms()["report"] is Report


async def test_the_defaults_match_the_harness(tmp_path: Path):
    app = form_app(Report(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, run=RUN_ID)
        spec = view.review()
        assert spec == actions.report(Workspace(tmp_path), RESULTS)
        assert spec is not None and spec.steps[0].argv == ("report", "--results", str(RESULTS.resolve()))


async def test_a_cutoff_and_a_page_reach_the_builder(tmp_path: Path):
    app = form_app(Report(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, run=RUN_ID, cutoff="2026-10-01", html=True)
        spec = view.review()
        assert spec is not None
        name = Path(spec.outputs[0].path).stem
        assert spec == actions.report(Workspace(tmp_path), RESULTS, cutoff="2026-10-01", html=True, name=name)


async def test_a_summary_only_run_cant_be_picked_and_says_why(tmp_path: Path):
    app = form_app(Report(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        assert flat("summary rows can't be reported on") in flat(screen_text(app))
        fill(view, run=SHIPPED_LIVE)
        assert view.review() is None
        assert (
            row_errors(view)["run"] == "That run only has summary rows, so there's no results file to read."
        )


async def test_a_bad_cutoff_is_caught_on_the_field(tmp_path: Path):
    app = form_app(Report(), sample_store(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, run=RUN_ID, cutoff="2026-02-30")
        assert view.review() is None
        assert row_errors(view) == {"cutoff": "2026-02-30 isn't a real date."}


async def test_the_confirm_step_shows_the_builders_command(tmp_path: Path):
    app = GauntletApp(sample_store(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "report")
        view = screen.forms["report"]
        view.workspace = Workspace(tmp_path)
        fill(view, run=RUN_ID, html=True)
        spec = view.review()
        await pilot.pause()
        assert spec is not None and isinstance(app.screen, ConfirmJob)
        text = screen_text(app)
        assert flat(f"$ {command_line(spec.steps[0])}") in flat(text)
        assert "nothing but this machine" in text


async def test_it_wont_start_without_a_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runner = FakeJobRunner()

    def broken():
        raise OSError("can't read free disk")

    monkeypatch.setattr(runner, "machine", broken)
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "report")
        view = screen.forms["report"]
        fill(view, run=RUN_ID)
        assert view.review() is None
        assert view.banner.error == NO_WORKSPACE
        assert runner.submitted == []


async def test_a_finished_report_opens_as_tables(tmp_path: Path):
    spec = actions.report(Workspace(tmp_path), RESULTS, html=True, name=NAME)
    runner = FakeJobRunner()
    runner.script("report", [*real_report(), f"wrote {spec.outputs[0].path}"])
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        assert "✓ succeeded" in screen_text(app)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, ReportScreen)
        text = screen_text(app)
        assert "SWE: single-PR tasks" in text and "Policy" in text and "|---|" not in text
        assert app.screen.query_one(ReportView).blocks
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, JobScreen)


async def test_a_report_on_a_broken_file_reads_as_failed(tmp_path: Path):
    spec = actions.report(Workspace(tmp_path), RESULTS)
    runner = FakeJobRunner()
    runner.script("report", [("pydantic_core.ValidationError: 1 validation error", "err")], exit_code=1)
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        text = screen_text(app)
        assert "✗ failed" in text and "found something" not in text and "ValidationError" in text


async def test_fits_at_80_by_24(tmp_path: Path):
    spec = actions.report(Workspace(tmp_path), RESULTS, html=True, name=NAME)
    runner = FakeJobRunner()
    runner.script("report", real_report())
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "report")
        await settle(app, pilot)
        assert screen.forms["report"].has_class("-stacked")
        assert "Run" in screen_text(app)
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await pilot.press("o")
        await settle(app, pilot)
        text = screen_text(app)
        assert isinstance(app.screen, ReportScreen) and "Policy" in text
        assert "Quit" in text.splitlines()[-1]


@pytest.mark.parametrize("html", [True, False])
async def test_the_leaderboard_shows_in_the_result_pane_with_or_without_a_page(tmp_path: Path, html: bool):
    spec = actions.report(Workspace(tmp_path), RESULTS, html=html, name=NAME)
    runner = FakeJobRunner()
    runner.script("report", real_report())
    app = GauntletApp(sample_store(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        screen = await open_job(app, pilot, record.id)
        await settle(app, pilot)
        pane = screen.query_one("#job-outcome")
        assert pane.display and pane.query_one(ReportOutcome).query_one(ReportView).blocks
        assert "Policy" in screen_text(app)
