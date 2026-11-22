import argparse
import io
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import SelectionList

from gauntlet.harness import cli
from gauntlet.harness.lht import range_id
from gauntlet.harness.schema import Rejected
from gauntlet.tui import actions
from gauntlet.tui.actions import ReleaseRange
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.workbench import ActionList, WorkbenchScreen
from gauntlet.tui.widgets.buildresult import BuildResult
from gauntlet.tui.widgets.form import FormBanner, FormView
from gauntlet.tui.widgets.rangelister import ListerStatus, RangeLister, range_choices
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.make_lht_tasks import MakeLhtTasks
from gauntlet.tui.workspace import Workspace

from .factories import make_source, screen_text
from .fakejobs import FakeJobRunner, fake_machine, fill, form_app, row_errors
from .sample import SAMPLE_DATASETS
from .wait import settle, wait_until

WIDE = (140, 40)
SMALL = (80, 24)
STAMP = datetime(2026, 11, 22, 9, 30, 0)
REPO = "pytest-dev/pluggy"
RANGES = (ReleaseRange("1.4.0", "1.5.0", 3, 1), ReleaseRange("1.5.0", "1.6.0", 12, 0))
LISTED = [
    "  cloning",
    ("progress", "err"),
    *(f"{r.from_ref}\t{r.to_ref}\t{r.prs} PRs\t{r.direct_commits} direct commits" for r in RANGES),
]
MAX_PRS = 12
GOLD_LINES = 900
FAILED_CLONE = 128
OUTPUT_FLAGS = {"output", "rejected", "fn", "cmd", "verbose"}


def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "work", clock=lambda: STAMP)


def runner_for(tmp_path: Path, **machine) -> FakeJobRunner:
    """A runner whose machine check names the test's workspace, as the real one would."""
    return FakeJobRunner(machine=fake_machine(workspace=str(tmp_path / "work"), **machine))


@pytest.fixture
def parse(monkeypatch):
    """Runs argv through `gauntlet`'s real parser and returns what it parsed."""
    seen: list[argparse.Namespace] = []
    for attr in dir(cli):
        if attr.startswith("cmd_"):
            monkeypatch.setattr(cli, attr, lambda args: seen.append(args) or 0)

    def run(argv) -> dict[str, object]:
        assert cli.main(list(argv)) == 0
        return {k: v for k, v in vars(seen.pop()).items() if k not in OUTPUT_FLAGS}

    return run


async def open_form(app: GauntletApp, pilot, tmp_path: Path) -> tuple[WorkbenchScreen, FormView]:
    await settle(app, pilot)
    await pilot.press("5")
    await settle(app, pilot)
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, WorkbenchScreen)
    options = screen.query_one(ActionList)
    options.highlighted = options.get_option_index("make_lht_tasks")
    await pilot.pause()
    view = screen.forms["make_lht_tasks"]
    view.workspace = workspace(tmp_path)
    return screen, view


async def until(pilot, check) -> None:
    """Pause until `check()` holds, so a slow machine doesn't race the job events."""
    await wait_until(pilot, check)


def status(app: GauntletApp) -> str:
    view = app.screen.query_one(ListerStatus)
    return f"{view.state}: {view.message}"


async def list_ranges(app: GauntletApp, pilot, runner: FakeJobRunner, view: FormView, **values) -> None:
    """Fill the repo, press List ranges, start it on the confirm step and run it to the end."""
    fill(view, **{"repo": REPO, **values})
    view.query_one("#list-ranges").press()
    await settle(app, pilot)
    assert isinstance(app.screen, ConfirmJob)
    await pilot.press("enter")
    await settle(app, pilot)
    runner.run_until_idle()
    await settle(app, pilot)
    await until(pilot, lambda: not status(app).startswith("listing"))


def test_the_form_is_found():
    assert forms()["make_lht_tasks"] is MakeLhtTasks


def test_range_choices_line_up_and_carry_the_range():
    choices = range_choices(RANGES)
    assert [c.value for c in choices] == ["1.4.0..1.5.0", "1.5.0..1.6.0"]
    assert choices[0].label == "1.4.0  to  1.5.0   3 PRs, 1 direct commit"
    assert choices[1].label == "1.5.0  to  1.6.0  12 PRs, 0 direct commits"
    assert range_choices(()) == ()


async def test_listing_runs_in_the_form_and_fills_the_ranges(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen, view = await open_form(app, pilot, tmp_path)
        assert "A range is the work between two release tags" in screen_text(app)
        fill(view, repo=REPO, last="2")
        view.query_one("#list-ranges").press()
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmJob)
        assert app.screen.spec == actions.list_ranges(REPO, last=2)
        assert "$ gauntlet ranges --repo pytest-dev/pluggy --last 2" in screen_text(app)
        await pilot.press("enter")
        await settle(app, pilot)
        assert app.screen is screen and runner.submitted[-1].action == "list_ranges"
        await until(pilot, lambda: status(app).startswith("listing:"))
        runner.step()
        await settle(app, pilot)
        assert status(app).startswith("listing: Listing the ranges of pytest-dev/pluggy")
        runner.run_until_idle()
        await settle(app, pilot)
        await until(pilot, lambda: status(app).startswith("found:"))
        assert status(app) == "found: 2 ranges of pytest-dev/pluggy. Pick the ones to build under Ranges."
        ranges = view.row("ranges").control
        assert isinstance(ranges, SelectionList) and ranges.option_count == len(RANGES)
        assert ranges.selected == []
        assert app.screen is screen


async def test_picking_ranges_builds_the_builders_command(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view)
        fill(
            view,
            ranges=("1.5.0..1.6.0",),
            fix_runs="3",
            python="3.11",
            max_prs=str(MAX_PRS),
            max_gold_lines=str(GOLD_LINES),
            scope="changed",
            name="pluggy-lht",
        )
        view.review()
        await settle(app, pilot)
        assert isinstance(app.screen, ConfirmJob)
        assert app.screen.spec == actions.make_lht_tasks(
            workspace(tmp_path),
            REPO,
            ranges=[RANGES[1]],
            python="3.11",
            fix_runs=3,
            max_prs=MAX_PRS,
            max_gold_lines=GOLD_LINES,
            scope="changed",
            name="pluggy-lht",
        )
        assert "$ gauntlet build-lht --repo pytest-dev/pluggy --range 1.5.0..1.6.0" in screen_text(app)


async def test_defaults_are_the_harness_defaults(tmp_path: Path, parse):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view)
        fill(view, ranges=("1.4.0..1.5.0",), name="pluggy")
        spec = view.review()
        assert spec == actions.make_lht_tasks(workspace(tmp_path), REPO, ranges=[RANGES[0]], name="pluggy")
        built = parse(spec.steps[0].argv)
        assert built == parse(["build-lht", "--repo", REPO, "--range", "1.4.0..1.5.0"])
        listing = runner.submitted[0]
        assert parse(listing.steps[0].argv) == parse(["ranges", "--repo", REPO])


async def test_a_repo_with_no_tags_says_so(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", [("  cloning", "err")])
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view)
        assert status(app).startswith("none: pytest-dev/pluggy has no release ranges.")
        assert "Turn on Prereleases" in status(app)
        fill(view, ranges=())
        assert view.review() is None
        await pilot.pause()
        error = view.query_one(FormBanner).error
        assert error is not None and "Pick at least one release range" in error


async def test_no_tags_with_prereleases_on_drops_the_tip(tmp_path: Path):
    runner = runner_for(tmp_path)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view, prereleases=True)
        assert status(app).startswith("none:") and "Prereleases" not in status(app)


async def test_a_failed_listing_says_why_and_opens_its_log(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", [("fatal: repository not found", "err")], exit_code=FAILED_CLONE)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view)
        assert status(app).startswith("failed: Listing failed: List release ranges exited with code 128")
        assert view.row("ranges").control.option_count == 0
        view.query_one("#ranges-log").press()
        await settle(app, pilot)
        assert isinstance(app.screen, JobScreen) and "repository not found" in screen_text(app)


async def test_a_cancelled_listing_can_be_tried_again(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        fill(view, repo=REPO)
        view.query_one("#list-ranges").press()
        await settle(app, pilot)
        await pilot.press("enter")
        await settle(app, pilot)
        await until(pilot, lambda: status(app).startswith("listing:"))
        runner.cancel(runner.jobs()[0].id)
        await settle(app, pilot)
        await until(pilot, lambda: status(app).startswith("cancelled:"))
        assert status(app).startswith("cancelled: Listing was cancelled")


async def test_docker_down_blocks_the_build_but_not_the_listing(tmp_path: Path):
    runner = runner_for(tmp_path, docker_running=False, docker_detail="no daemon")
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        assert view.blocked is not None and "Docker isn't running" in view.blocked
        await list_ranges(app, pilot, runner, view)
        assert status(app).startswith("found:")
        fill(view, ranges=("1.4.0..1.5.0",))
        assert view.review() is None
        await settle(app, pilot)
        assert not isinstance(app.screen, ConfirmJob)
        assert [s.action for s in runner.submitted] == ["list_ranges"]


async def test_building_before_listing_or_for_another_repo_is_refused(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        fill(view, repo=REPO)
        assert view.review() is None
        assert "List the repo's release ranges first" in (view.query_one(FormBanner).error or "")
        await list_ranges(app, pilot, runner, view)
        fill(view, repo="hukkin/tomli", ranges=("1.4.0..1.5.0",))
        assert view.review() is None
        error = view.query_one(FormBanner).error or ""
        assert "The ranges below are pytest-dev/pluggy's. List the ranges of hukkin/tomli first." in error


@pytest.mark.parametrize(
    ("values", "field", "words"),
    [
        ({"repo": ""}, "repo", "needed"),
        ({"repo": "pluggy"}, "repo", "owner/name"),
        ({"last": "0"}, "last", "from 1"),
        ({"fix_runs": "0"}, "fix_runs", "from 1"),
        ({"max_prs": "many"}, "max_prs", "whole number"),
        ({"max_gold_lines": str(actions.MAX_GOLD_LINES + 1)}, "max_gold_lines", "from 1"),
        ({"python": ""}, "python", "needed"),
    ],
)
async def test_every_field_validates(tmp_path: Path, values, field, words):
    app = form_app(MakeLhtTasks(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        view = app.query_one(FormView)
        fill(view, **{"repo": REPO, **values})
        assert view.review() is None
        assert words in row_errors(view)[field]


async def test_the_lister_checks_its_own_fields_and_the_builders_rules(tmp_path: Path):
    app = form_app(MakeLhtTasks(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await settle(app, pilot)
        view = app.query_one(FormView)
        fill(view, repo="nope")
        view.query_one(RangeLister).ask()
        assert "owner/name" in row_errors(view)["repo"]
        fill(view, repo=REPO, repo_url="nowhere-at-all")
        view.query_one(RangeLister).ask()
        assert status(app).startswith("refused:") and "git URL" in status(app)
        fill(view, repo_url="")
        view.query_one(RangeLister).ask()
        assert status(app) == "refused: There's no job runner here, so the ranges can't be listed."


async def test_the_real_ranges_output_fills_the_form(tmp_path: Path, monkeypatch, capsys):
    from ..harness.fakerelease import REPO as FAKE_REPO
    from ..harness.fakerelease import make_release_repo

    upstream = make_release_repo(tmp_path / "up")
    monkeypatch.setenv("GAUNTLET_CACHE", str(tmp_path / "cache"))
    assert cli.main(["ranges", "--repo", FAKE_REPO, "--repo-url", str(upstream)]) == 0
    printed = capsys.readouterr().out.splitlines()
    runner = runner_for(tmp_path)
    runner.script("list_ranges", printed)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view, repo=FAKE_REPO, repo_url=str(upstream))
        assert runner.submitted[0].needs == ()
        assert view.row("ranges").control.option_count == len(printed)
        fill(view, ranges=("v0.1.0..v0.2.0",))
        spec = view.review()
        assert spec is not None and ("--range", "v0.1.0..v0.2.0") == spec.steps[0].argv[5:7]
        assert ("--repo-url", str(upstream.resolve())) == spec.steps[0].argv[3:5]


def result_text(app: GauntletApp) -> str:
    console = Console(width=WIDE[0], file=io.StringIO(), record=True)
    console.print(app.screen.query_one(BuildResult).render())
    return console.export_text()


async def test_the_build_result_names_kept_and_rejected_ranges(tmp_path: Path):
    spec = actions.make_lht_tasks(workspace(tmp_path), REPO, ranges=RANGES, name="pluggy")
    paths = {o.kind: Path(o.path) for o in spec.outputs}
    paths["tasks"].parent.mkdir(parents=True)
    paths["tasks"].write_text(
        (SAMPLE_DATASETS / "gauntlet-mini-lht" / "tasks.jsonl").read_text().splitlines()[0] + "\n"
    )
    rejected = Rejected(
        instance_id=range_id(REPO, "1.5.0", "1.6.0"),
        stage="filter",
        reason="the source diff is 9000 lines, the cap is 6000",
    )
    paths["rejected"].write_text(rejected.model_dump_json() + "\n")
    runner = runner_for(tmp_path)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=SMALL) as pilot:
        await open_form(app, pilot, tmp_path)
        record = runner.submit(spec)
        app.remember_job(record)
        app.open_job(record.id)
        await settle(app, pilot)
        runner.run_until_idle()
        await settle(app, pilot)
        await settle(app, pilot)
        assert "1 task built from 2 release ranges, 1 rejected." in screen_text(app)
        text = result_text(app)
        assert "1.4.0..1.5.0" in text and "Rejected at filter  1" in text
        assert "1.5.0..1.6.0" in text and "the cap is 6000" in text


async def test_it_fits_at_80_by_24(tmp_path: Path):
    runner = runner_for(tmp_path)
    runner.script("list_ranges", LISTED)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=SMALL) as pilot:
        _, view = await open_form(app, pilot, tmp_path)
        await list_ranges(app, pilot, runner, view)
        view.row("ranges").scroll_visible(animate=False)
        await settle(app, pilot)
        assert "1.4.0  to  1.5.0" in screen_text(app)
