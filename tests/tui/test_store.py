import math

import pytest

from gauntlet.cheatcatcher import RULES
from gauntlet.harness.cli import CALIBRATION_POLICIES, calibration_violations
from gauntlet.harness.schema import EpisodeResult, GradeResult
from gauntlet.tui import store as store_module
from gauntlet.tui.models import NotFound

from .sample import (
    CONFBOX,
    LHT_ID,
    LIVE_ID,
    PLUGGY,
    RUN_ID,
    SAMPLE_DATASETS,
    SHIPPED_LHT,
    SHIPPED_LIVE,
    SLUGIFY_LHT,
    TOMLI,
    TOMLI_ORACLE,
    sample_store,
)


@pytest.fixture(scope="module")
def store():
    return sample_store()


def test_overview_counts_what_was_loaded(store):
    o = store.overview()
    assert o.totals.tasks == 4
    assert o.totals.repos == 4
    assert o.totals.datasets == 2
    assert o.totals.runs == 3
    assert o.totals.episodes == 18
    assert o.totals.leak_checks_per_task == len(store_module.LEAK_CHECKS)
    assert o.totals.leak_check_failures == 0
    assert o.totals.cheat_policies == sum(1 for p in CALIBRATION_POLICIES if p.startswith("cheater"))
    assert o.totals.cheatcatcher_rules == len(RULES)
    assert o.warnings == ()
    assert [d.id for d in o.datasets] == [LHT_ID, LIVE_ID]
    assert {r.id for r in o.runs} == {SHIPPED_LHT, SHIPPED_LIVE, RUN_ID}


def test_datasets_summarize_their_tasks(store):
    live = next(d for d in store.datasets() if d.id == LIVE_ID)
    assert live.title == "gauntlet-mini-live"
    assert live.tasks == 2 and live.repos == 2
    assert {f.id: f.count for f in live.runners} == {"pytest": 1, "vitest": 1}
    assert {f.id for f in live.categories} == {"swe"}
    assert live.merged_from is not None and live.merged_from <= live.merged_to
    assert live.has_validation and live.leakcheck_ok == 2


def test_dataset_detail_reads_stats(store):
    live = store.dataset(LIVE_ID)
    assert live.prs_collected == 186
    assert [f.id for f in live.rejected_by_stage] == ["filter", "transitions", "statement"]
    assert {f.id for f in live.by_repo} == {"hukkin/tomli", "unjs/confbox"}
    lht = store.dataset(LHT_ID)
    assert lht.prs_collected is None and lht.rejected_by_stage == ()


def test_old_task_rows_load_the_way_the_harness_loads_them(store):
    row = store.tasks(query=TOMLI)[0]
    assert row.category == "swe" and row.runner == "pytest" and row.language == "python"
    js = store.task(CONFBOX).row
    assert js.runner == "vitest" and js.language == "node"


def test_task_filters_and_facets(store):
    assert {r.instance_id for r in store.tasks(dataset=LHT_ID)} == {PLUGGY, SLUGIFY_LHT}
    assert [r.instance_id for r in store.tasks(repo="unjs/confbox")] == [CONFBOX]
    assert {r.instance_id for r in store.tasks(category="lht")} == {PLUGGY, SLUGIFY_LHT}
    assert [r.instance_id for r in store.tasks(runner="vitest")] == [CONFBOX]
    assert [r.instance_id for r in store.tasks(query="TOMLI")] == [TOMLI]
    assert store.tasks(dataset=LIVE_ID, category="lht") == ()
    facets = store.task_facets()
    assert {f.id: f.count for f in facets.datasets} == {LIVE_ID: 2, LHT_ID: 2}
    assert {f.id: f.count for f in facets.categories} == {"swe": 2, "lht": 2}
    assert [f.id for f in facets.runners] == ["pytest", "vitest"]
    assert len(facets.repos) == 4


def test_task_detail(store):
    t = store.task(PLUGGY)
    assert t.row.horizon is not None and t.horizon is not None
    assert t.row.horizon.milestones == len(t.horizon.milestones)
    assert t.row.pr_number is None
    assert [c.id for c in t.leakchecks] == [check_id for check_id, _, _ in store_module.LEAK_CHECKS]
    assert all(c.ok and c.detail for c in t.leakchecks)
    assert t.validation is not None and t.validation.fix_runs == len(t.validation.fix)
    assert (
        t.validation.test.total
        == t.validation.test.passed + t.validation.test.failed + t.validation.test.skipped
    )
    assert t.gold_patch.startswith("diff --git") and not t.gold_patch_truncated
    assert {e.run_id for e in t.episodes} == {RUN_ID, SHIPPED_LHT}
    swe = store.task(TOMLI)
    assert swe.horizon is None and swe.row.pr_number == 318


def test_task_tests_lists_one_class(store):
    t = store.task(PLUGGY)
    assert store.task_tests(PLUGGY, "f2p") == t.f2p
    p2p = store.task_tests(PLUGGY, "p2p")
    assert len(p2p) == t.row.p2p
    narrowed = store.task_tests(PLUGGY, "p2p", query=p2p[0].upper())
    assert p2p[0] in narrowed and len(narrowed) < len(p2p)


def test_long_patches_are_cut_and_marked(store, monkeypatch):
    monkeypatch.setattr(store_module, "PATCH_LIMIT", 10)
    t = store.task(PLUGGY)
    assert len(t.gold_patch) == 10 and t.gold_patch_truncated
    e = store.episode(RUN_ID, TOMLI_ORACLE)
    assert e.patch is not None and len(e.patch) == 10 and e.patch_truncated


def test_unknown_ids_raise_not_found(store):
    calls = [
        lambda: store.dataset("nope"),
        lambda: store.task("nope"),
        lambda: store.task_tests("nope", "f2p"),
        lambda: store.run("nope"),
        lambda: store.matrix("nope"),
        lambda: store.episode_facets("nope"),
        lambda: store.episodes("nope"),
        lambda: store.episode(RUN_ID, "nope"),
        lambda: store.episode("nope", TOMLI_ORACLE),
        lambda: store.episode_tests(RUN_ID, "nope"),
        lambda: store.trajectory(RUN_ID, "nope"),
    ]
    for call in calls:
        with pytest.raises(NotFound):
            call()


def test_reference_rules_follow_the_registry(store):
    ref = store.reference()
    assert [r.id for r in ref.rules] == list(RULES)
    assert [r.what for r in ref.rules] == [fn.__doc__.strip().splitlines()[0] for fn in RULES.values()]


def test_reference_leak_checks_match_the_recorded_ones(store):
    ref = store.reference()
    recorded = {c.id for t in (TOMLI, CONFBOX, PLUGGY, SLUGIFY_LHT) for c in store.task(t).leakchecks}
    assert {c.id for c in ref.leak_checks} == recorded
    assert all(c.title and c.what for c in ref.leak_checks)


def test_reference_policies_and_steps(store):
    ref = store.reference()
    named = [p for p in ref.policies if p.kind != "model"]
    assert [p.id for p in named] == CALIBRATION_POLICIES
    assert all(p.what for p in ref.policies)
    assert {p.kind for p in ref.policies} == {"oracle", "noop", "cheat", "model"}
    ids = [s.id for s in ref.grading_steps]
    assert len(ids) == len(set(ids))
    assert (
        ids.index("scan")
        < ids.index("apply")
        < ids.index("canary")
        < ids.index("tamper")
        < ids.index("reward")
    )


def _violations(policy, reward, *, resolved):
    grade = GradeResult(instance_id="t", patch_applied=True, resolved=resolved)
    row = EpisodeResult(episode_id="e", instance_id="t", policy=policy, reward=reward, grade=grade)
    return calibration_violations([row])


def test_thresholds_sit_exactly_where_the_calibration_rule_flips(store):
    th = store.reference().thresholds
    assert not _violations("oracle", th.oracle_min_reward, resolved=True)
    assert _violations("oracle", math.nextafter(th.oracle_min_reward, -math.inf), resolved=True)
    assert not _violations("noop", th.noop_reward, resolved=False)
    assert _violations("noop", math.nextafter(th.noop_reward, math.inf), resolved=False)
    assert not _violations("cheater:exit", th.cheat_max_reward, resolved=False)
    assert _violations("cheater:exit", math.nextafter(th.cheat_max_reward, math.inf), resolved=False)


def test_search_ranks_prefix_before_substring(store):
    hits = store.search("mini", limit=10)
    assert [h.id for h in hits[:2]] == [LHT_ID, LIVE_ID]
    assert {h.id for h in hits[2:]} >= {SHIPPED_LHT, SHIPPED_LIVE}
    tomli = store.search("HUKKIN", limit=3)
    assert tomli[0].kind == "task" and tomli[0].id == TOMLI
    assert all(h.kind == "episode" and h.run_id for h in tomli[1:])


def test_search_finds_episodes_in_every_run_and_respects_the_limit(store):
    hits = store.search(f"{PLUGGY}__oracle__0", limit=10)
    assert {h.run_id for h in hits} == {RUN_ID, SHIPPED_LHT}
    assert len(store.search("__", limit=3)) == 3
    assert store.search("  ", limit=5) == ()
    assert store.search("tomli", limit=0) == ()


def test_search_matches_repo_names(store):
    hits = store.search("unjs/conf", limit=5)
    assert hits[0].kind == "task" and hits[0].id == CONFBOX


def test_datasets_root_can_be_left_out():
    from gauntlet.tui.store import Store

    s = Store.load(None, [])
    assert s.overview().totals.tasks == 0 and s.datasets() == () and s.runs() == ()
    assert SAMPLE_DATASETS.is_dir()
