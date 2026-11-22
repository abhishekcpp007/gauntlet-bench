"""Each builder's commands, parsed by the harness's real argument parser."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pytest

from gauntlet.cheatcatcher import cli as cheatcatcher_cli
from gauntlet.harness import cli
from gauntlet.harness.cli import CALIBRATION_POLICIES
from gauntlet.harness.runner import episode_id
from gauntlet.harness.schema import HarnessTask
from gauntlet.tui import actions
from gauntlet.tui.actions import (
    ACTIONS,
    ActionError,
    ReleaseRange,
    check_policies,
    parse_ranges,
    parse_scan,
)
from gauntlet.tui.workspace import Workspace

from .sample import SAMPLE_DATASETS, SAMPLE_RUN, TOMLI

STAMP = datetime(2026, 11, 22, 9, 30, 0)
LIVE_TASKS = SAMPLE_DATASETS / "gauntlet-mini-live" / "tasks.jsonl"
RESULTS = SAMPLE_RUN / "results.jsonl"
EXAMPLES = Path(__file__).resolve().parents[1] / "cheatcatcher" / "examples"
CHEAT_DIFF = EXAMPLES / "conftest_force_pass.diff"
HONEST_DIFF = EXAMPLES / "honest_fix.diff"
OUTPUT_FLAGS = {"output", "rejected", "prs", "tasks", "results", "fn", "cmd", "verbose", "html"}
LIMIT = 7
FIX_RUNS = 3
WORKERS = 4
ATTEMPTS = 3
SAMPLE = 5
MAX_STEPS = 80
MAX_EPISODES = 10
MAX_TOKENS = 1_000_000
MAX_SECONDS = 600.0
MAX_USD = 2.5
LAST = 2
MAX_PRS = 12
GOLD_LINES = 900


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "work", clock=lambda: STAMP)


@pytest.fixture
def patch(tmp_path):
    path = tmp_path / "answer.diff"
    path.write_text(HONEST_DIFF.read_text())
    return path


@pytest.fixture
def parse(monkeypatch):
    """Runs argv through `gauntlet`'s real parser and returns the parsed namespace."""
    seen: list[argparse.Namespace] = []

    def capture(args: argparse.Namespace) -> int:
        seen.append(args)
        return 0

    for module in (cli, cheatcatcher_cli):
        for attr in dir(module):
            if attr.startswith("cmd_"):
                monkeypatch.setattr(module, attr, capture)

    def run(argv) -> argparse.Namespace:
        assert all(isinstance(a, str) for a in argv)
        assert cli.main(list(argv)) == 0
        return seen.pop()

    return run


def _same_defaults(a: argparse.Namespace, b: argparse.Namespace) -> None:
    left = {k: v for k, v in vars(a).items() if k not in OUTPUT_FLAGS}
    right = {k: v for k, v in vars(b).items() if k not in OUTPUT_FLAGS}
    assert left == right


# ---------------------------------------------------------------------- catalogue


def test_the_catalogue_follows_the_brief_table():
    assert [a.id for a in ACTIONS] == [
        "make_tasks",
        "make_lht_tasks",
        "leakcheck",
        "check_envs",
        "calibrate",
        "run_policies",
        "try_patch",
        "scan_patch",
        "report",
    ]
    assert [a.group for a in ACTIONS] == [
        "make",
        "make",
        "check",
        "check",
        "check",
        "score",
        "score",
        "score",
        "score",
    ]
    for info in ACTIONS:
        assert hasattr(actions, info.id)
        assert "—" not in info.description and info.description.endswith(".")
        for word in ("comprehensive", "robust", "seamless", "efficient", "ensure", "utilize", "intuitive"):
            assert word not in info.description.lower()
    assert {a.id: a.needs for a in ACTIONS}["scan_patch"] == ()


# ---------------------------------------------------------------------- make tasks


def test_make_tasks_builds_collect_then_build(ws, parse):
    spec = actions.make_tasks(
        ws,
        ["pallets/click", "hukkin/tomli"],
        merged_after="2026-06-01",
        limit=LIMIT,
        scope="changed",
        fix_runs=FIX_RUNS,
        python="3.11",
        git_fallback=True,
    )
    folder = ws.root / "tasks" / "pallets-click-20261122-093000"
    collect, build = (parse(s.argv) for s in spec.steps)
    assert collect.repo == ["pallets/click", "hukkin/tomli"] and collect.merged_after == "2026-06-01"
    assert collect.limit == LIMIT and collect.git_fallback and collect.output == str(folder / "prs.jsonl")
    assert build.prs == collect.output and build.output == str(folder / "tasks.jsonl")
    assert build.rejected == str(folder / "rejected.jsonl")
    assert (build.python, build.scope, build.fix_runs, build.no_leakcheck) == (
        "3.11",
        "changed",
        FIX_RUNS,
        False,
    )
    assert spec.needs == ("docker", "network") and spec.exclusive
    assert [o.kind for o in spec.outputs] == ["tasks", "rejected", "prs"]
    assert not folder.exists()


def test_make_tasks_defaults_are_the_harness_defaults(ws, parse):
    spec = actions.make_tasks(ws, ["a/b"], name="mine")
    _same_defaults(parse(spec.steps[0].argv), parse(["collect", "--repo", "a/b"]))
    _same_defaults(parse(spec.steps[1].argv), parse(["build", "--prs", "x"]))


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"repos": []}, "at least one repo"),
        ({"repos": ["click"]}, "owner/name"),
        ({"repos": ["-x/y"]}, "owner/name"),
        ({"repos": ["a/b; rm -rf /"]}, "owner/name"),
        ({"merged_after": "2026-13-01"}, "YYYY-MM-DD"),
        ({"merged_after": "1 June"}, "YYYY-MM-DD"),
        ({"limit": 0}, "PR limit"),
        ({"limit": True}, "PR limit"),
        ({"scope": "most"}, "scope"),
        ({"fix_runs": 0}, "Fix runs"),
        ({"python": "three"}, "Python"),
        ({"name": "../escape"}, "folder name"),
    ],
)
def test_make_tasks_refuses_bad_input(ws, kwargs, words):
    args = {"repos": ["a/b"], **kwargs}
    with pytest.raises(ActionError, match=words):
        actions.make_tasks(ws, args.pop("repos"), **args)


def test_list_ranges(parse, tmp_path):
    spec = actions.list_ranges("acme/calc", repo_url=str(tmp_path), last=LAST, prereleases=True)
    args = parse(spec.steps[0].argv)
    assert (args.repo, args.repo_url, args.last, args.prereleases) == ("acme/calc", str(tmp_path), LAST, True)
    assert spec.needs == () and not spec.exclusive
    assert actions.list_ranges("acme/calc").needs == ("network",)
    _same_defaults(parse(actions.list_ranges("a/b").steps[0].argv), parse(["ranges", "--repo", "a/b"]))
    with pytest.raises(ActionError, match="git URL"):
        actions.list_ranges("a/b", repo_url="nowhere-at-all")


def test_parse_ranges_reads_the_real_command_output(tmp_path, monkeypatch, capsys):
    from ..harness.fakerelease import REPO, make_release_repo

    upstream = make_release_repo(tmp_path / "up")
    monkeypatch.setenv("GAUNTLET_CACHE", str(tmp_path / "cache"))
    assert cli.main(["ranges", "--repo", REPO, "--repo-url", str(upstream)]) == 0
    printed = capsys.readouterr().out.splitlines()
    found = parse_ranges(["  progress on stderr", *printed, ""])
    assert [(r.from_ref, r.to_ref) for r in found] == [("v0.1.0", "v0.2.0"), ("v0.1.0", "v0.1.1")]
    assert all(r.prs >= 0 and r.direct_commits >= 0 for r in found)
    assert len(found) == len(printed)


def test_parse_ranges_by_hand():
    lines = ["v1.0\tv1.1\t3 PRs\t2 direct commits\n", "junk", "a\tb\tmany PRs\t0 direct commits"]
    assert parse_ranges(lines) == (ReleaseRange("v1.0", "v1.1", 3, 2),)
    assert parse_ranges(lines)[0].spec == "v1.0..v1.1"


def test_make_lht_tasks(ws, parse, tmp_path):
    spec = actions.make_lht_tasks(
        ws,
        "acme/calc",
        ranges=[ReleaseRange("v0.1.0", "v0.2.0", 1, 0), "v0.1.0..v0.1.1"],
        repo_url=str(tmp_path),
        max_prs=MAX_PRS,
        max_gold_lines=GOLD_LINES,
        name="calc-lht",
    )
    args = parse(spec.steps[0].argv)
    assert args.range == ["v0.1.0..v0.2.0", "v0.1.0..v0.1.1"] and args.last is None
    assert args.output == str(ws.root / "tasks" / "calc-lht" / "tasks.jsonl")
    assert args.rejected == str(ws.root / "tasks" / "calc-lht" / "rejected.jsonl")
    assert (args.max_prs, args.max_gold_lines, args.repo_url) == (MAX_PRS, GOLD_LINES, str(tmp_path))
    newest = parse(actions.make_lht_tasks(ws, "acme/calc", last=LAST).steps[0].argv)
    assert newest.last == LAST and newest.range is None
    _same_defaults(
        parse(actions.make_lht_tasks(ws, "a/b").steps[0].argv), parse(["build-lht", "--repo", "a/b"])
    )


@pytest.mark.parametrize("bad", ["v1", "v1..", "..v2", "-x..v2", "v1..v2..v3", "v1 ..v2"])
def test_make_lht_tasks_refuses_bad_ranges(ws, bad):
    with pytest.raises(ActionError):
        actions.make_lht_tasks(ws, "a/b", ranges=[bad])


# ---------------------------------------------------------------------- check


def test_leakcheck_and_check_envs(parse):
    spec = actions.leakcheck(LIVE_TASKS)
    assert parse(spec.steps[0].argv).tasks == str(LIVE_TASKS.resolve())
    assert spec.needs == ("docker", "network") and spec.exclusive
    envs = actions.check_envs([LIVE_TASKS, LIVE_TASKS])
    assert parse(envs.steps[0].argv).tasks == [str(LIVE_TASKS.resolve())] * 2
    assert envs.needs == ("network",) and not envs.exclusive
    with pytest.raises(ActionError, match="doesn't exist"):
        actions.leakcheck("/no/such/tasks.jsonl")
    with pytest.raises(ActionError, match="at least one"):
        actions.check_envs([])


def test_calibrate(ws, parse):
    spec = actions.calibrate(ws, LIVE_TASKS, sample=SAMPLE, seed="2026-11-22", workers=WORKERS, name="cal")
    args = parse(spec.steps[0].argv)
    assert (args.sample, args.seed, args.workers) == (SAMPLE, "2026-11-22", WORKERS)
    assert args.policies == ",".join(CALIBRATION_POLICIES)
    assert args.output == str(ws.root / "runs" / "cal")
    assert spec.outputs[0].kind == "run" and spec.needs == ("docker", "network")
    _same_defaults(
        parse(actions.calibrate(ws, LIVE_TASKS).steps[0].argv), parse(["calibrate", "--tasks", "x"])
    )
    with pytest.raises(ActionError, match="seed"):
        actions.calibrate(ws, LIVE_TASKS, seed="--evil")


# ---------------------------------------------------------------------- score


def test_run_policies_with_every_flag(ws, parse, patch):
    spec = actions.run_policies(
        ws,
        LIVE_TASKS,
        f"oracle, claude:claude-opus-5-5 ,patch:{patch}",
        attempts=ATTEMPTS,
        workers=WORKERS,
        category="swe",
        max_steps=MAX_STEPS,
        max_episodes=MAX_EPISODES,
        max_tokens=MAX_TOKENS,
        max_seconds=MAX_SECONDS,
        max_usd=MAX_USD,
        prices="claude:=3/15",
        name="sweep",
    )
    args = parse(spec.steps[0].argv)
    assert args.policies == f"oracle,claude:claude-opus-5-5,patch:{patch.resolve()}"
    assert (args.attempts, args.workers, args.category, args.max_steps) == (
        ATTEMPTS,
        WORKERS,
        "swe",
        MAX_STEPS,
    )
    assert (args.max_episodes, args.max_tokens, args.max_seconds, args.max_usd) == (
        MAX_EPISODES,
        MAX_TOKENS,
        MAX_SECONDS,
        MAX_USD,
    )
    assert args.prices == "claude:=3/15" and args.output == str(ws.root / "runs" / "sweep")
    assert spec.needs == ("docker", "network", "api_key")


def test_run_policies_defaults_match_and_need_no_key(ws, parse):
    spec = actions.run_policies(ws, LIVE_TASKS, ["oracle", "noop", "cheater"])
    assert "api_key" not in spec.needs
    _same_defaults(parse(spec.steps[0].argv), parse(["run", "--tasks", "x"]))


@pytest.mark.parametrize(
    ("kwargs", "words"),
    [
        ({"policies": "gpt-9"}, "unknown policy"),
        ({"policies": " , "}, "at least one policy"),
        ({"policies": ["oracle,noop"]}, "comma"),
        ({"policies": "patch:/no/such.diff"}, "doesn't exist"),
        ({"attempts": 0}, "Attempts"),
        ({"workers": 1000}, "Workers"),
        ({"category": "web"}, "category"),
        ({"max_steps": -1}, "Max steps"),
        ({"max_seconds": 0}, "Max seconds"),
        ({"max_usd": 1.0}, "needs prices"),
        ({"prices": "claude=3"}, "Prices"),
        ({"prices": "claude:=a/b"}, "Prices"),
    ],
)
def test_run_policies_refuses_bad_input(ws, kwargs, words):
    args = {"policies": "oracle", **kwargs}
    with pytest.raises(ActionError, match=words):
        actions.run_policies(ws, LIVE_TASKS, args.pop("policies"), **args)


def test_check_policies_asks_the_harness():
    assert check_policies("oracle,cheater:ghost") == ("oracle", "cheater:ghost")
    with pytest.raises(ActionError, match="cheater:nope"):
        check_policies(["cheater:nope"])


def test_try_patch_copies_the_task_line_and_predicts_the_episode(ws, parse, patch):
    spec = actions.try_patch(ws, LIVE_TASKS, TOMLI, patch, name="try-1")
    run_dir = ws.root / "runs" / "try-1"
    one = run_dir / "task.jsonl"
    lines = LIVE_TASKS.read_bytes().splitlines(keepends=True)
    line = next(x for x in lines if json.loads(x)["instance_id"] == TOMLI)
    assert one.read_bytes() == line
    args = parse(spec.steps[0].argv)
    assert args.tasks == str(one) and args.output == str(run_dir)
    assert args.policies == f"patch:{patch.resolve()}" and (args.attempts, args.workers) == (
        actions.ATTEMPTS,
        actions.TRY_PATCH_WORKERS,
    )
    episode = spec.outputs[0]
    assert episode.kind == "run" and episode.path == str(run_dir)
    task = HarnessTask.model_validate_json(line)
    assert episode.episode_id == episode_id(task, args.policies, actions.TRY_PATCH_ATTEMPT)
    assert episode.episode_id.startswith(f"{TOMLI}__patch-") and "/" not in episode.episode_id


def test_try_patch_refuses_an_unknown_task(ws, patch):
    with pytest.raises(ActionError, match="no task"):
        actions.try_patch(ws, LIVE_TASKS, "nobody__nothing-1", patch)
    assert not (ws.root / "runs").exists()


def test_try_patch_refuses_a_comma_in_the_patch_path(ws, tmp_path):
    bad = tmp_path / "a,b.diff"
    bad.write_text(HONEST_DIFF.read_text())
    with pytest.raises(ActionError, match="comma"):
        actions.try_patch(ws, LIVE_TASKS, TOMLI, bad)


def test_scan_patch_treats_suspicious_and_cheating_as_a_finished_scan(parse, tmp_path):
    traj = tmp_path / "t.jsonl"
    traj.write_text("")
    spec = actions.scan_patch(CHEAT_DIFF, protect=["tests/test_x.py", "conftest.py"], trajectory=traj)
    args = parse(spec.steps[0].argv)
    assert args.patch == str(CHEAT_DIFF.resolve()) and args.json
    assert args.protect == ["tests/test_x.py", "conftest.py"] and args.trajectory == str(traj)
    assert set(spec.steps[0].ok_codes) == {
        cheatcatcher_cli.EXIT_CODES[v] for v in ("clean", "suspicious", "cheating")
    }
    assert spec.needs == () and not spec.exclusive
    with pytest.raises(ActionError, match="inside the repo"):
        actions.scan_patch(CHEAT_DIFF, protect=["--json"])
    with pytest.raises(ActionError, match="inside the repo"):
        actions.scan_patch(CHEAT_DIFF, protect=["../outside.py"])


def test_parse_scan():
    text = (
        "warning first\n"
        '{"findings": [{"rule": "outcome-forcing", "severity": "high", "message": "m", "step": null,'
        ' "file": "conftest.py", "evidence": "e"}], "verdict": "cheating"}\n'
    )
    result = parse_scan(text)
    assert result.verdict == "cheating" and result.findings[0].file == "conftest.py"
    assert parse_scan('{"findings": []}').verdict == "clean"
    for bad in ("nothing here", "{not json", '{"findings": [{"rule": 1}]}'):
        with pytest.raises(ActionError):
            parse_scan(bad)


def test_report(ws, parse):
    spec = actions.report(ws, RESULTS, cutoff="2026-06-01", html=True)
    args = parse(spec.steps[0].argv)
    assert args.results == str(RESULTS.resolve()) and args.cutoff == "2026-06-01"
    assert args.html == str(ws.root / "reports" / "sample-run-20261122-093000.html")
    assert (ws.root / "reports").is_dir()
    assert spec.outputs[0].kind == "report" and not spec.exclusive and spec.needs == ()
    plain = parse(actions.report(ws, RESULTS).steps[0].argv)
    assert plain.html is None and plain.cutoff is None
    dotted = parse(actions.report(ws, RESULTS, html=True, name="v1.2").steps[0].argv)
    assert dotted.html.endswith("v1.2.html")


def test_runs_default_policies_come_from_its_own_parser(parse, monkeypatch):
    assert actions.RUN_POLICIES == tuple(parse(["run", "--tasks", "x"]).policies.split(","))


def test_reading_the_parser_runs_no_command_and_puts_argparse_back(monkeypatch):
    import argparse as real_argparse

    def must_not_run(_args):
        raise AssertionError("a command ran")

    monkeypatch.setattr(cli, "cmd_run", must_not_run)
    parsed = actions.harness_parse("run", "--tasks", "x", "--attempts", "3")
    assert parsed.attempts == 3 and parsed.tasks == "x"
    assert cli.argparse is real_argparse
