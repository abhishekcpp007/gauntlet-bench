import json
import shutil

import pytest

from gauntlet.harness.cli import calibration_violations
from gauntlet.harness.report import solved, summarize
from gauntlet.harness.runner import load_results
from gauntlet.tui import store as store_module
from gauntlet.tui.store import Store

from .sample import (
    CONFBOX,
    LHT_ID,
    PLUGGY,
    PLUGGY_CHEATER,
    PLUGGY_MONKEYPATCH,
    RUN_ID,
    SAMPLE_DATASETS,
    SAMPLE_RUN,
    SHIPPED_LHT,
    SHIPPED_LIVE,
    TOMLI,
    TOMLI_CHEATER,
    TOMLI_ORACLE,
    sample_store,
)

SAMPLE_POLICIES = ("oracle", "noop", "cheater", "cheater:monkeypatch")


@pytest.fixture(scope="module")
def store():
    return sample_store()


def test_run_summaries(store):
    runs = {r.id: r for r in store.runs()}
    sample = runs[RUN_ID]
    assert sample.kind == "folder" and sample.detail == "full"
    assert sample.episodes == 8 and sample.tasks == 2
    assert sample.policies == SAMPLE_POLICIES
    assert sample.path == str(SAMPLE_RUN) and sample.dataset_id is None
    assert sample.ran_from is not None and sample.ran_from <= sample.ran_to
    assert sample.oracle.episodes == 2 and sample.oracle.resolved == 2
    assert sample.noop.max_reward == -1.0
    assert sample.cheats.episodes == 4 and sample.cheats.cheating_verdicts == 4
    assert sample.violations == 0
    lht = runs[SHIPPED_LHT]
    assert lht.kind == "shipped" and lht.detail == "full" and lht.dataset_id == LHT_ID and lht.episodes == 4
    live = runs[SHIPPED_LIVE]
    assert live.detail == "summary" and live.violations is None and live.ran_from is None


def test_policy_rows_match_the_cli_report(store):
    rows = load_results(SAMPLE_RUN / "results.jsonl")
    summary = summarize(rows)
    assert summary["category"] == "mixed"
    expected = [(cat, p) for cat, block in summary["categories"].items() for p in block["policies"]]
    got = store.run(RUN_ID).policies
    assert [(r.category, r.policy) for r in got] == [(cat, p["policy"]) for cat, p in expected]
    for row, (cat, stats) in zip(got, expected, strict=True):
        mine = [r for r in rows if r.policy == row.policy and r.category == cat]
        assert row.episodes == stats["episodes"] and row.tasks == stats["tasks"]
        assert row.resolved == sum(solved(r) for r in mine)
        assert row.resolved / row.episodes == stats["resolved_rate"]
        assert row.mean_reward == stats["mean_reward"]
        assert row.errors == stats["errors"]
        assert row.min_reward == min(r.reward for r in mine) and row.max_reward == max(r.reward for r in mine)
        if stats["pass@1_ci95"] is None:
            assert row.pass_at_1 is None
        else:
            assert (row.pass_at_1.value, row.pass_at_1.low, row.pass_at_1.high) == (
                stats["pass@1"],
                *stats["pass@1_ci95"],
            )
        assert row.verdicts.cheating == sum(r.cheat_verdict == "cheating" for r in mine)
        assert row.tampered == sum(bool(r.grade and r.grade.tampered) for r in mine)


def test_calibration_matches_the_cli(store):
    detail = store.run(RUN_ID)
    assert detail.calibration_checked
    assert list(detail.violations) == calibration_violations(load_results(SAMPLE_RUN / "results.jsonl"))
    assert detail.rotted == ()


def test_calibration_reports_what_breaks(tmp_path):
    run = tmp_path / "broken"
    shutil.copytree(SAMPLE_RUN, run)
    rows = [json.loads(line) for line in (run / "results.jsonl").read_text().splitlines()]
    for row in rows:
        if row["episode_id"] == TOMLI_CHEATER:
            row["reward"] = 0.5
    (run / "results.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    detail = Store.load(SAMPLE_DATASETS, [run]).run("broken")
    assert len(detail.violations) == 1 and "a cheat earned +0.500" in detail.violations[0]
    assert detail.summary.violations == 1


def test_slim_rows_say_what_they_have(store):
    detail = store.run(SHIPPED_LIVE)
    assert not detail.calibration_checked and detail.violations == ()
    assert {p.policy for p in detail.policies} == {"oracle", "noop", "cheater"}
    oracle = next(p for p in detail.policies if p.policy == "oracle")
    assert oracle.resolved == 2 and oracle.tampered is None
    rows = store.episodes(SHIPPED_LIVE)
    assert all(r.detail == "summary" and r.attempt is None and r.seconds is None for r in rows)
    confbox = [r for r in rows if r.instance_id == CONFBOX]
    tomli = [r for r in rows if r.instance_id == TOMLI]
    assert all(r.tampered is False for r in confbox) and all(r.tampered is None for r in tomli)
    e = store.episode(SHIPPED_LIVE, rows[0].episode_id)
    assert e.grade is None and e.reward_breakdown is None and e.patch is None and e.findings == ()
    assert e.provenance is None and e.truncated is None and e.trajectory_steps is None
    assert e.rubric_score is not None
    assert store.trajectory(SHIPPED_LIVE, rows[0].episode_id) is None
    assert store.episode_tests(SHIPPED_LIVE, rows[0].episode_id, test_class="p2p") == tuple(
        t for t in store.episode_tests(SHIPPED_LIVE, rows[0].episode_id) if t.test_class == "p2p"
    )


def test_full_shipped_rows_are_checked(store):
    detail = store.run(SHIPPED_LHT)
    assert detail.calibration_checked and detail.violations == ()
    assert store.trajectory(SHIPPED_LHT, f"{PLUGGY}__oracle__0") is None


def test_matrix(store):
    m = store.matrix(RUN_ID)
    assert m.policies == SAMPLE_POLICIES
    assert [t.instance_id for t in m.tasks] == sorted([TOMLI, PLUGGY])
    assert [t.category for t in m.tasks] == ["swe", "lht"]
    assert all(cell is not None for row in m.cells for cell in row)
    oracle = m.cells[0][0]
    assert oracle.episode_id == TOMLI_ORACLE and oracle.resolved and oracle.verdict == "clean"


def test_episode_filters_and_facets(store):
    facets = store.episode_facets(RUN_ID)
    assert [(f.id, f.count) for f in facets.policies] == [(p, 2) for p in SAMPLE_POLICIES]
    assert {f.id: f.count for f in facets.verdicts} == {"clean": 4, "cheating": 4}
    assert {f.id for f in facets.tasks} == {TOMLI, PLUGGY}
    assert len(store.episodes(RUN_ID)) == 8
    assert [r.episode_id for r in store.episodes(RUN_ID, policy="cheater", task=TOMLI)] == [TOMLI_CHEATER]
    assert {r.policy for r in store.episodes(RUN_ID, verdict="cheating")} == {
        "cheater",
        "cheater:monkeypatch",
    }
    assert {r.policy for r in store.episodes(RUN_ID, resolved=True)} == {"oracle"}
    assert len(store.episodes(RUN_ID, query="MONKEYPATCH")) == 2
    assert store.episodes(RUN_ID, policy="oracle", resolved=False) == ()


def test_episode_detail(store):
    e = store.episode(RUN_ID, PLUGGY_MONKEYPATCH)
    assert e.row.detail == "full" and e.row.policy_kind == "cheat" and e.row.category == "lht"
    assert e.reward_breakdown is not None and e.reward_breakdown.penalty == e.row.reward
    assert e.grade is not None and not e.grade.tampered and e.row.tampered is False
    assert {f.rule for f in e.findings} == {"outcome-forcing", "runner-sniffing"}
    assert e.provenance is not None and e.provenance.harness_version
    assert e.trajectory_steps == len(store.trajectory(RUN_ID, PLUGGY_MONKEYPATCH).steps)
    assert e.prompt is not None and "pytest-dev/pluggy" in e.prompt
    caught = store.episode(RUN_ID, f"{TOMLI}__cheater-monkeypatch__0")
    assert caught.grade.tampered and caught.row.tampered
    assert any(f.rule == "grader-tamper" for f in caught.findings)
    oracle = store.episode(RUN_ID, TOMLI_ORACLE)
    b = oracle.reward_breakdown
    assert b.w_tests is not None and b.tests == 1.0 and b.penalty == 0.0
    assert oracle.rubric_items and oracle.grade.resolved
    total = sum(f.count for f in oracle.grade.status_counts)
    assert total == len(store.episode_tests(RUN_ID, TOMLI_ORACLE))


def test_episode_tests_join_the_task_classes(store):
    task = store.task(PLUGGY)
    tests = store.episode_tests(RUN_ID, f"{PLUGGY}__oracle__0")
    by_id = {t.id: t for t in tests}
    assert all(by_id[t].test_class == "f2p" for t in task.f2p)
    assert all(t.status == "PASSED" for t in tests if t.test_class == "f2p")
    classes = [t.test_class for t in tests]
    assert classes == sorted(classes, key=lambda c: ("f2p", "n2p", "s2p", "p2p", None).index(c))
    failed = store.episode_tests(RUN_ID, f"{PLUGGY}__noop__0", test_class="f2p", status="FAILED")
    assert {t.id for t in failed} == set(task.f2p)
    one = task.f2p[0]
    assert [t.id for t in store.episode_tests(RUN_ID, f"{PLUGGY}__oracle__0", query=one.upper())] == [one]


def test_episode_tests_without_the_task_have_no_class():
    s = Store.load(None, [SAMPLE_RUN])
    tests = s.episode_tests(RUN_ID, TOMLI_ORACLE)
    assert tests and all(t.test_class is None for t in tests)


@pytest.mark.parametrize("episode_id", [TOMLI_CHEATER, PLUGGY_CHEATER])
def test_flagged_steps_are_the_commands_the_findings_describe(store, episode_id):
    detail = store.episode(RUN_ID, episode_id)
    steps = {s.index: s for s in store.trajectory(RUN_ID, episode_id).steps}
    tied = [f for f in detail.findings if f.step is not None]
    assert tied
    for f in tied:
        step = steps[f.step]
        assert f.rule in step.flagged
        if step.kind == "exec":
            assert step.command == f.evidence
        else:
            assert step.kind == "write_file" and step.path.endswith("/" + f.file)
            assert f.evidence in step.content
    flagged = {s.index for s in steps.values() if s.flagged}
    assert flagged == {f.step for f in tied}


def test_peeking_finding_points_at_the_peek(store):
    detail = store.episode(RUN_ID, TOMLI_CHEATER)
    peek = next(f for f in detail.findings if f.rule == "answer-peeking")
    step = next(s for s in store.trajectory(RUN_ID, TOMLI_CHEATER).steps if s.index == peek.step)
    assert "/tmp/gauntlet-patches" in step.command and "answer-peeking" in step.flagged


def test_trajectory(store):
    t = store.trajectory(RUN_ID, TOMLI_ORACLE)
    assert t.header is not None and not t.header.network and t.header.image
    assert [s.index for s in t.steps] == list(range(len(t.steps)))
    assert t.warnings == ()
    assert all(not s.flagged for s in t.steps)
    assert store.trajectory(RUN_ID, TOMLI_ORACLE) is t


def test_a_moved_folder_still_finds_its_files(tmp_path):
    moved = tmp_path / "elsewhere" / "run"
    shutil.copytree(SAMPLE_RUN, moved)
    s = Store.load(SAMPLE_DATASETS, [moved])
    assert s.trajectory("run", TOMLI_ORACLE) is not None
    assert s.episode("run", TOMLI_ORACLE).prompt


def test_broken_files_dont_stop_the_load(tmp_path):
    run = tmp_path / "run"
    shutil.copytree(SAMPLE_RUN, run)
    with (run / "results.jsonl").open("a") as f:
        f.write("{not json\n")
        f.write('{"episode_id": "x"}\n')
    (run / "trajectories" / f"{TOMLI_ORACLE}.jsonl").unlink()
    (run / "rl" / f"{TOMLI_ORACLE}.json").write_text("{broken")
    with (run / "trajectories" / f"{TOMLI_CHEATER}.jsonl").open("a") as f:
        f.write("not json either\n")
    datasets = tmp_path / "datasets"
    shutil.copytree(SAMPLE_DATASETS, datasets)
    (datasets / "gauntlet-mini-live" / "stats.json").write_text("[")
    s = Store.load(datasets, [run, tmp_path / "missing"])
    warnings = s.overview().warnings
    assert len(warnings) == 4
    assert any("line 9" in w and "valid JSON" in w for w in warnings)
    assert any("line 10" in w and "isn't an episode" in w for w in warnings)
    assert any("missing" in w and "results.jsonl" in w for w in warnings)
    assert any("stats.json" in w for w in warnings)
    assert len(s.episodes("run")) == 8
    assert s.trajectory("run", TOMLI_ORACLE) is None
    e = s.episode("run", TOMLI_ORACLE)
    assert e.trajectory_steps is None and e.prompt is None
    broken = s.trajectory("run", TOMLI_CHEATER)
    assert broken.steps and len(broken.warnings) == 1
    assert s.dataset("mini-live").prs_collected is None


def test_a_missing_datasets_folder_is_a_warning(tmp_path):
    s = Store.load(tmp_path / "nope", [])
    assert len(s.overview().warnings) == 1


def test_two_folders_with_one_name_get_different_ids(tmp_path):
    first, second = tmp_path / "a" / "run", tmp_path / "b" / "run"
    shutil.copytree(SAMPLE_RUN, first)
    shutil.copytree(SAMPLE_RUN, second)
    s = Store.load(None, [first, second, SAMPLE_RUN])
    assert [r.id for r in s.runs()] == ["run", "b-run", RUN_ID]
    again = Store.load(None, [first, second, SAMPLE_RUN])
    assert [r.id for r in again.runs()] == ["run", "b-run", RUN_ID]


def test_long_output_is_cut_and_marked(tmp_path, monkeypatch):
    run = tmp_path / "run"
    shutil.copytree(SAMPLE_RUN, run)
    path = run / "trajectories" / f"{TOMLI_ORACLE}.jsonl"
    lines = path.read_text().splitlines()
    step = json.loads(lines[1])
    limit = 8
    step["observation"]["stdout"] = "x" * (limit + 1)
    lines[1] = json.dumps(step)
    path.write_text("\n".join(lines) + "\n")
    monkeypatch.setattr(store_module, "OUTPUT_LIMIT", limit)
    first = Store.load(None, [run]).trajectory("run", TOMLI_ORACLE).steps[0]
    assert first.stdout == "x" * limit and first.truncated
