"""The Workbench end to end, for real: the app, the real `SubprocessJobRunner` on a temp workspace,
the real `Store` over the fixtures, and a real `gauntlet cheatcatcher scan` child process. No
Docker and no network: the machine check is the only thing swapped out, since it calls Docker."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.jobs import SubprocessJobRunner
from gauntlet.tui.jobtypes import FINISHED
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.workbench import ActionList, WorkbenchScreen
from gauntlet.tui.store import Store
from gauntlet.tui.widgets.grid import DataGrid
from gauntlet.tui.widgets.joblog import LogLines
from gauntlet.tui.workspace import Workspace

from .factories import screen_text
from .fakejobs import fake_machine, fill
from .sample import SAMPLE_DATASETS, SAMPLE_RUN
from .wait import settle, wait_until

EXAMPLES = Path(__file__).resolve().parents[1] / "cheatcatcher" / "examples"
CHEATING_DIFF = EXAMPLES / "conftest_force_pass.diff"
SIZE = (140, 40)
REAL_TIMEOUT_SECONDS = 60.0
POLL_SECONDS = 0.1
CHEATING_EXIT = 2


def start(root: Path) -> GauntletApp:
    workspace = Workspace(root)
    machine = replace(fake_machine(), workspace=str(workspace.root))
    runner = SubprocessJobRunner(workspace, machine=lambda: machine)
    store = Store.load(SAMPLE_DATASETS, [SAMPLE_RUN], workspace=workspace.root)
    return GauntletApp(store, jobs=runner, reload=store.reload)


async def open_workbench(app: GauntletApp, pilot) -> WorkbenchScreen:
    await settle(app, pilot)
    await pilot.press("5")
    await settle(app, pilot)
    assert isinstance(app.screen, WorkbenchScreen)
    return app.screen


async def test_scan_a_cheating_patch_through_a_real_process(tmp_path: Path):
    root = tmp_path / "work"
    app = start(root)
    async with app.run_test(size=SIZE) as pilot:
        screen = await open_workbench(app, pilot)
        actions = screen.query_one(ActionList)
        actions.highlighted = actions.get_option_index("scan_patch")
        await pilot.pause()
        fill(screen.forms["scan_patch"], patch=CHEATING_DIFF)
        screen.forms["scan_patch"].review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        command = f"gauntlet cheatcatcher scan --patch {CHEATING_DIFF} --json"
        assert "".join(command.split()) in "".join(screen_text(app).replace("│", "").split())
        await pilot.press("enter")
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen)
        job_id = app.screen.job_id
        jobs = app.jobs
        assert jobs is not None
        await wait_until(
            pilot,
            lambda: jobs.job(job_id).state in FINISHED,
            what="the scan to finish",
            timeout=REAL_TIMEOUT_SECONDS,
        )
        await settle(app, pilot)
        await settle(app, pilot)
        record = jobs.job(job_id)
        assert record.state == "succeeded" and record.exit_code == CHEATING_EXIT
        text = screen_text(app)
        assert "✓ succeeded" in text and "exit 2" in text
        assert "● cheating" in text and "finding" in text
        log = app.screen.query_one(LogLines)
        assert any('"verdict": "cheating"' in line.text for line in log.lines)
        log_path = Path(record.log_path)
        assert log_path.is_relative_to(root.resolve()) and log_path.read_text().strip()

    again = start(root)
    async with again.run_test(size=SIZE) as pilot:
        screen = await open_workbench(again, pilot)
        await pilot.press("right_square_bracket")
        await settle(again, pilot)
        grid = screen.query_one("#job-grid", DataGrid)
        assert [r.id for r in grid.rows] == [job_id]
        assert "Scan conftest_force_pass.diff" in screen_text(again)
        await pilot.press("enter")
        await settle(again, pilot)
        await settle(again, pilot)
        assert isinstance(again.screen, JobScreen)
        assert "● cheating" in screen_text(again)
