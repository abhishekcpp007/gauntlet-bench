import argparse
import io
import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from rich.console import Console
from textual.widgets import OptionList

from gauntlet.harness import cli
from gauntlet.harness.schema import PRInfo, Rejected
from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.jobtypes import JobSpec
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.screens.dataset import DatasetScreen
from gauntlet.tui.screens.job import JobScreen
from gauntlet.tui.screens.workbench import ActionList, WorkbenchScreen
from gauntlet.tui.widgets.buildresult import BuildResult
from gauntlet.tui.widgets.form import FormBanner, FormView
from gauntlet.tui.widgets.formextras import FormNote
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.make_tasks import LIVE_PRS, LIVE_TASKS, MakeTasks
from gauntlet.tui.workspace import Workspace

from .factories import LIVE, make_source, screen_text
from .fakejobs import NEXT_STEP, FakeJobRunner, fill, form_app, row_errors
from .sample import REPO_DATASETS, SAMPLE_DATASETS, TOMLI

WIDE = (140, 40)
SMALL = (80, 24)
STAMP = datetime(2026, 11, 22, 9, 30, 0)
LIMIT = 7
FIX_RUNS = 3
NO_TASKS = 1
TOMLI_TITLE = "Set smaller MAX_INLINE_NESTING"
HOSTILE = "[red]x[/red] \x1b[31mboom"
PATIENCE = 50
STEP_SECONDS = 0.1
OUTPUT_FLAGS = {"output", "rejected", "prs", "fn", "cmd", "verbose"}


def workspace(tmp_path: Path) -> Workspace:
    return Workspace(tmp_path / "work", clock=lambda: STAMP)


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


async def settle(app, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause(0.1)


async def mounted_form(app, pilot) -> FormView:
    await settle(app, pilot)
    await settle(app, pilot)
    return app.query_one(FormView)


def test_the_form_is_found():
    assert forms()["make_tasks"] is MakeTasks


def test_the_live_funnel_it_quotes_is_the_shipped_one():
    stats = json.loads((REPO_DATASETS / "gauntlet-live-2026-11" / "stats.json").read_text())
    assert (stats["prs_collected"], stats["tasks"]) == (LIVE_PRS, LIVE_TASKS)


async def test_defaults_are_the_harness_defaults(tmp_path: Path, parse):
    ws = workspace(tmp_path)
    app = form_app(MakeTasks(), workspace=ws.root)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted_form(app, pilot)
        view.workspace = ws
        fill(view, repos="a/b", name="mine")
        spec = view.review()
        assert spec == actions.make_tasks(ws, ["a/b"], name="mine")
        collect, build = (parse(step.argv) for step in spec.steps)
        assert collect == parse(["collect", "--repo", "a/b"])
        assert build == parse(["build", "--prs", "x"])


async def test_every_field_reaches_the_builder(tmp_path: Path):
    ws = workspace(tmp_path)
    app = form_app(MakeTasks(), workspace=ws.root)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted_form(app, pilot)
        view.workspace = ws
        fill(
            view,
            repos="pallets/click, hukkin/tomli",
            merged_after="2026-06-01",
            limit=str(LIMIT),
            scope="changed",
            fix_runs=str(FIX_RUNS),
            python="3.11",
            git_fallback=True,
        )
        spec = view.review()
        assert spec == actions.make_tasks(
            workspace(tmp_path),
            ["pallets/click", "hukkin/tomli"],
            merged_after="2026-06-01",
            limit=LIMIT,
            scope="changed",
            fix_runs=FIX_RUNS,
            python="3.11",
            git_fallback=True,
        )


@pytest.mark.parametrize(
    ("values", "field", "words"),
    [
        ({"repos": ""}, "repos", "needed"),
        ({"repos": "click"}, "repos", "owner/name"),
        ({"repos": "a/b c;d"}, "repos", "owner/name"),
        ({"merged_after": "2026-13-01"}, "merged_after", "real date"),
        ({"merged_after": "1 June"}, "merged_after", "2026-11-05"),
        ({"limit": "0"}, "limit", "from 1"),
        ({"limit": "lots"}, "limit", "whole number"),
        ({"fix_runs": str(actions.MAX_FIX_RUNS + 1)}, "fix_runs", "from 1"),
        ({"python": ""}, "python", "needed"),
    ],
)
async def test_every_field_validates(tmp_path: Path, values, field, words):
    app = form_app(MakeTasks(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted_form(app, pilot)
        fill(view, **{"repos": "a/b", **values})
        assert view.review() is None
        assert words in row_errors(view)[field]


@pytest.mark.parametrize(
    ("values", "words"), [({"python": "three"}, "Python"), ({"name": "../up"}, "folder")]
)
async def test_the_builders_refusal_shows_on_top(tmp_path: Path, values, words):
    app = form_app(MakeTasks(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted_form(app, pilot)
        fill(view, repos="a/b", **values)
        assert view.review() is None
        await pilot.pause()
        error = view.query_one(FormBanner).error
        assert error is not None and words in error


async def test_the_form_says_what_it_costs_and_how_few_prs_make_a_task(tmp_path: Path):
    app = form_app(MakeTasks(), workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        await mounted_form(app, pilot)
        note = app.query_one(FormNote).text
        assert f"kept {LIVE_TASKS} tasks from {LIVE_PRS} PRs" in note
        intro = view_intro(app)
        assert "Docker" in intro and "network" in intro and f"run {actions.SUITE_RUNS} times" in intro
        text = screen_text(app)
        assert "Full runs the whole suite" in text and "flaky" in text


async def open_form(app: GauntletApp, pilot, ws: Workspace) -> tuple[WorkbenchScreen, FormView]:
    await settle(app, pilot)
    await pilot.press("5")
    await settle(app, pilot)
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, WorkbenchScreen)
    actions_list = screen.query_one(ActionList)
    actions_list.highlighted = actions_list.get_option_index("make_tasks")
    await pilot.pause()
    view = screen.forms["make_tasks"]
    view.workspace = ws
    return screen, view


async def test_confirm_shows_the_builders_command_lines(tmp_path: Path):
    ws = workspace(tmp_path)
    app = GauntletApp(make_source(), jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        _, view = await open_form(app, pilot, ws)
        fill(view, repos="pallets/click", limit=str(LIMIT))
        view.review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        assert app.screen.spec == actions.make_tasks(workspace(tmp_path), ["pallets/click"], limit=LIMIT)
        text = screen_text(app)
        assert (
            "$ gauntlet collect --repo pallets/click --limit 7 -o" in text
            and "$ gauntlet build --prs" in text
        )
        assert "1. Collect merged PRs" in text and "2. Build and leak-check tasks" in text


def tomli_task() -> str:
    tasks = SAMPLE_DATASETS / "gauntlet-mini-live" / "tasks.jsonl"
    return next(line for line in tasks.read_text().splitlines() if f'"{TOMLI}"' in line)


def write_files(spec: JobSpec, *, kept: bool, title: str = "Docs only") -> None:
    paths = {o.kind: Path(o.path) for o in spec.outputs}
    paths["tasks"].parent.mkdir(parents=True, exist_ok=True)
    prs = [
        PRInfo(repo="hukkin/tomli", number=318, title=TOMLI_TITLE, url="u"),
        PRInfo(repo="hukkin/tomli", number=2, title=title, url="u"),
        PRInfo(repo="hukkin/tomli", number=3, title="Pin CI", url="u"),
    ]
    rejected = [
        Rejected(instance_id="hukkin__tomli-2", stage="filter", reason="no Python source changes"),
        Rejected(
            instance_id="hukkin__tomli-3", stage="transitions", reason="no test goes from failing to passing"
        ),
    ]
    if not kept:
        rejected.append(Rejected(instance_id=f"{TOMLI}", stage="leak", reason="statement_quotes_fix"))
    paths["prs"].write_text("".join(p.model_dump_json() + "\n" for p in prs))
    paths["rejected"].write_text("".join(r.model_dump_json() + "\n" for r in rejected))
    paths["tasks"].write_text(tomli_task() + "\n" if kept else "")


async def run_build(
    tmp_path: Path, *, kept: bool, size=WIDE, title: str = "Docs only", exit_code: int | None = None
) -> tuple[GauntletApp, FakeJobRunner, JobSpec]:
    ws = workspace(tmp_path)
    spec = actions.make_tasks(ws, ["hukkin/tomli"], name="tomli")
    source = make_source()
    shown = tuple(
        replace(d, tasks_file=spec.outputs[0].path, from_workspace=True) if d.id == LIVE else d
        for d in source.datasets()
    )
    source.datasets = lambda: shown  # type: ignore[method-assign]  # a test double
    runner = FakeJobRunner()
    code = exit_code if exit_code is not None else (0 if kept else NO_TASKS)
    runner.script("make_tasks", ["collected 3 PRs", NEXT_STEP, ("  hukkin/tomli#318", "err")], exit_code=code)
    write_files(spec, kept=kept, title=title)
    return GauntletApp(source, jobs=runner), runner, spec


async def finish(app: GauntletApp, pilot, runner: FakeJobRunner, spec: JobSpec) -> JobScreen:
    await open_form(app, pilot, Workspace(Path(spec.outputs[0].path).parents[2]))
    record = runner.submit(spec)
    app.remember_job(record)
    app.open_job(record.id)
    await settle(app, pilot)
    runner.run_until_idle()
    await settle(app, pilot)
    screen = app.screen
    assert isinstance(screen, JobScreen)
    for _ in range(PATIENCE):
        results = screen.query(BuildResult)
        if spec.action != "make_tasks" or (results and results.first().summary is not None):
            break
        await pilot.pause(STEP_SECONDS)
    await settle(app, pilot)
    return screen


def result_text(app: GauntletApp) -> str:
    """Everything the build result says, scrolled or not."""
    console = Console(width=WIDE[0], file=io.StringIO(), record=True)
    console.print(app.screen.query_one(BuildResult).render())
    return console.export_text()


async def test_the_result_counts_and_groups_the_rejections(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=True)
    async with app.run_test(size=WIDE) as pilot:
        screen = await finish(app, pilot, runner, spec)
        assert screen.query_one("#job-outcome").display
        assert "1 task built from 3 PRs collected, 2 rejected." in screen_text(app)
        text = result_text(app)
        assert f"#318 {TOMLI_TITLE}" in text
        assert (
            "Rejected at filter  1" in text and "#2 Docs only" in text and "no Python source changes" in text
        )
        assert f"the shipped Live set kept {LIVE_TASKS} tasks from {LIVE_PRS} PRs" in text


async def test_o_opens_the_new_task_set(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=True)
    async with app.run_test(size=WIDE) as pilot:
        await finish(app, pilot, runner, spec)
        assert "o opens the new task set" in result_text(app)
        await pilot.press("o")
        await settle(app, pilot)
        assert isinstance(app.screen, DatasetScreen) and app.screen.dataset_id == LIVE


async def test_no_task_built_reads_as_a_normal_outcome(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=False)
    async with app.run_test(size=WIDE) as pilot:
        await finish(app, pilot, runner, spec)
        text = result_text(app)
        assert (
            "No task built from 3 PRs collected, 3 rejected. That's a normal outcome, not an error." in text
        )
        assert "gauntlet build exits 1 when it keeps no task, which is why the job reads failed." in text
        assert "Rejected at leak  1" in text and "o opens" not in text


async def test_a_crashed_build_says_it_stopped(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=False, exit_code=2)
    Path(spec.outputs[1].path).write_text(
        Rejected(instance_id="hukkin__tomli-2", stage="filter", reason="r").model_dump_json() + "\n"
    )
    async with app.run_test(size=WIDE) as pilot:
        await finish(app, pilot, runner, spec)
        text = screen_text(app)
        assert "The build stopped after 1 of 3 PRs." in text and "normal outcome" not in text


async def test_a_failed_collect_says_why_nothing_was_built(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=False)
    for path in (o.path for o in spec.outputs):
        Path(path).unlink()
    runner.script("make_tasks", ["error: GitHub rate limit"], exit_code=1)
    async with app.run_test(size=WIDE) as pilot:
        await finish(app, pilot, runner, spec)
        assert "Collecting PRs failed, so nothing was built" in screen_text(app)
        assert "Git fallback" in screen_text(app)


async def test_a_title_with_markup_shows_literally(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=True, title=HOSTILE)
    async with app.run_test(size=WIDE) as pilot:
        screen = await finish(app, pilot, runner, spec)
        assert "[red]x[/red] ^[[31mboom" in screen_text(app)
        assert screen.query_one(BuildResult).summary is not None


async def test_other_jobs_get_no_build_result(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=True)
    async with app.run_test(size=WIDE) as pilot:
        await finish(app, pilot, runner, replace(spec, action="calibrate"))
        assert not app.screen.query(BuildResult)


async def test_it_fits_at_80_by_24(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=True)
    async with app.run_test(size=SMALL) as pilot:
        await finish(app, pilot, runner, spec)
        text = screen_text(app)
        assert "1 task built from 3 PRs" in text
        await pilot.press("escape")
        await settle(app, pilot)
        assert "PR limit" in screen_text(app) or "Repos" in screen_text(app)


async def test_a_build_that_kept_nothing_wont_open_an_empty_task_set(tmp_path: Path):
    app, runner, spec = await run_build(tmp_path, kept=False)
    async with app.run_test(size=WIDE) as pilot:
        screen = await finish(app, pilot, runner, spec)
        assert screen.openable is not None
        assert [o.kind for o in screen.openable] == ["rejected", "prs"]
        listed = screen.query_one("#job-outputs").query_one(OptionList)
        assert listed.option_count == len(screen.openable)
        await pilot.press("o")
        await settle(app, pilot)
        assert not isinstance(app.screen, DatasetScreen)


def view_intro(app) -> str:
    """The action's description at the top of the form."""
    return str(app.query_one(FormView).info.description)
