from pathlib import Path

from gauntlet.tui import actions
from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.confirm import ConfirmJob
from gauntlet.tui.widgets.form import FormView
from gauntlet.tui.widgets.jobstatus import command_line
from gauntlet.tui.workbench import forms
from gauntlet.tui.workbench.run_policies import RUN_DEFAULT, RunPolicies
from gauntlet.tui.workspace import Workspace

from .factories import LIVE, make_source, screen_text
from .fakejobs import FakeJobRunner, fake_machine, fill, form_app, row_errors
from .test_actions import parse  # noqa: F401  # the fixture that runs argv through the real parser
from .test_form_examples import source_with_files
from .test_job_screen import open_job
from .test_workbench import open_workbench, pick, settle

WIDE = (140, 40)
SMALL = (80, 24)
MODEL = "claude:claude-opus-5-5"
EPISODE_FAILED = 1


def flat(text: str) -> str:
    return "".join(text.replace("│", "").split())


async def mounted(app, pilot) -> FormView:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app.query_one(FormView)


def test_the_default_policies_are_the_harness_defaults(parse):  # noqa: F811  # the imported fixture
    assert forms()["run_policies"] is RunPolicies
    assert tuple(parse(["run", "--tasks", "x"]).policies.split(",")) == RUN_DEFAULT


async def test_the_defaults_build_the_harness_defaults(tmp_path: Path, parse):  # noqa: F811
    source, tasks = source_with_files(tmp_path)
    app = form_app(RunPolicies(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        assert tuple(view.row("policies").control.selected) == RUN_DEFAULT
        fill(view, tasks=LIVE)
        spec = view.review()
        assert spec is not None
        built = parse(spec.steps[0].argv)
        default = parse(["run", "--tasks", str(tasks.resolve())])
        for flag in ("policies", "attempts", "workers", "category", "max_steps", "max_usd", "prices"):
            assert getattr(built, flag) == getattr(default, flag)
        assert "api_key" not in spec.needs


async def test_every_field_reaches_the_builder(tmp_path: Path):
    source, tasks = source_with_files(tmp_path)
    patch = tmp_path / "mine.diff"
    patch.write_text("diff --git a/x b/x\n")
    app = form_app(RunPolicies(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(
            view,
            tasks=LIVE,
            policies=("oracle", "cheater:ghost"),
            extra=f"{MODEL} patch:{patch}",
            attempts="3",
            workers="4",
            category="swe",
            max_steps="80",
            max_episodes="10",
            max_tokens="1000000",
            max_seconds="600",
            max_usd="2.5",
            prices="claude:=3/15",
        )
        spec = view.review()
        assert spec is not None
        name = Path(spec.outputs[0].path).name
        assert spec == actions.run_policies(
            Workspace(tmp_path),
            tasks,
            ("oracle", "cheater:ghost", MODEL, f"patch:{patch}"),
            attempts=3,
            workers=4,
            category="swe",
            max_steps=80,
            max_episodes=10,
            max_tokens=1_000_000,
            max_seconds=600.0,
            max_usd=2.5,
            prices="claude:=3/15",
            name=name,
        )
        assert "api_key" in spec.needs


async def test_fields_check_their_numbers_and_a_policy_is_needed(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = form_app(RunPolicies(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, tasks=LIVE, attempts="0", workers="many", max_steps="-1")
        assert view.review() is None
        assert set(row_errors(view)) == {"attempts", "workers", "max_steps"}
        fill(view, attempts="1", workers="2", max_steps="", policies=())
        assert view.review() is None
        assert view.banner.error == "Pick at least one policy"


async def test_a_dollar_cap_with_no_prices_shows_the_builders_message(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = form_app(RunPolicies(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, tasks=LIVE, max_usd="2.5")
        assert view.review() is None
        await pilot.pause()
        assert view.banner.error == "Max dollars needs prices, for example claude:=3/15"
        assert "Max dollars needs prices" in screen_text(app)


async def test_an_unknown_policy_shows_the_harness_message(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = form_app(RunPolicies(), source, workspace=tmp_path)
    async with app.run_test(size=WIDE) as pilot:
        view = await mounted(app, pilot)
        fill(view, tasks=LIVE, extra="gpt-9")
        assert view.review() is None
        assert "unknown policy 'gpt-9'" in (view.banner.error or "")


async def test_the_confirm_step_shows_the_command_and_the_model_credential(tmp_path: Path):
    source, tasks = source_with_files(tmp_path)
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "run_policies")
        view = screen.forms["run_policies"]
        view.workspace = Workspace(tmp_path)
        fill(view, tasks=LIVE, extra=MODEL)
        spec = view.review()
        await pilot.pause()
        assert spec is not None and isinstance(app.screen, ConfirmJob)
        text = screen_text(app)
        assert flat(f"$ {command_line(spec.steps[0])}") in flat(text)
        assert "oracle,noop,cheater,claude:claude-opus-5-5" in flat(text)
        assert "an Anthropic key" in text and "ANTHROPIC_API_KEY is set" in text


async def test_a_model_policy_with_no_key_wont_start(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    runner = FakeJobRunner(machine=fake_machine(anthropic_key_set=False))
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "run_policies")
        view = screen.forms["run_policies"]
        view.workspace = Workspace(tmp_path)
        fill(view, tasks=LIVE)
        view.review()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmJob)
        assert "an Anthropic key" not in screen_text(app)
        await pilot.press("escape")
        await pilot.pause()
        fill(view, extra=MODEL)
        view.review()
        await settle(app, pilot)
        assert not isinstance(app.screen, ConfirmJob)
        assert "ANTHROPIC_API_KEY isn't set" in screen_text(app)
        assert runner.submitted == []


async def test_no_docker_blocks_it(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    runner = FakeJobRunner(machine=fake_machine(docker_running=False, docker_detail="no daemon"))
    app = GauntletApp(source, jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "run_policies")
        view = screen.forms["run_policies"]
        fill(view, tasks=LIVE)
        assert view.review() is None
        assert "Docker isn't running (no daemon)" in screen_text(app)


async def finished(tmp_path: Path, lines: list[str], exit_code: int) -> tuple[str, str]:
    _, tasks = source_with_files(tmp_path)
    spec = actions.run_policies(Workspace(tmp_path), tasks, RUN_DEFAULT)
    runner = FakeJobRunner()
    runner.script("run_policies", lines, exit_code=exit_code)
    app = GauntletApp(make_source(), jobs=runner)
    async with app.run_test(size=WIDE) as pilot:
        record = runner.submit(spec)
        runner.run_until_idle()
        await open_job(app, pilot, record.id)
        await settle(app, pilot)
        text = screen_text(app)
        return text, text.splitlines()[-1]


async def test_a_finished_run_reads_as_succeeded_and_offers_the_run(tmp_path: Path):
    text, keys = await finished(tmp_path, ["oracle  hukkin__tomli-318  SOLVED reward=+1.000"], 0)
    assert "✓ succeeded" in text and "Made" in text and "Open" in keys


async def test_a_run_with_a_crashed_episode_reads_as_failed(tmp_path: Path):
    text, _ = await finished(
        tmp_path, ["oracle  hukkin__tomli-318  -  reward=+0.000 cheat=clean"], EPISODE_FAILED
    )
    assert "✗ failed" in text and "found something" not in text


async def test_fits_at_80_by_24(tmp_path: Path):
    source, _ = source_with_files(tmp_path)
    app = GauntletApp(source, jobs=FakeJobRunner())
    async with app.run_test(size=SMALL) as pilot:
        screen = await open_workbench(app, pilot)
        await pick(screen, pilot, "run_policies")
        await settle(app, pilot)
        assert screen.forms["run_policies"].has_class("-stacked")
        text = screen_text(app)
        assert "Task set" in text and "Quit" in text.splitlines()[-1]
