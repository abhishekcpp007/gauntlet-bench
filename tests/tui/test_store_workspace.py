"""The store loads a Workbench workspace's task sets and runs next to the shipped ones."""

import json
import shutil
from collections import Counter

from gauntlet.tui.store import Store

from .sample import LIVE_ID, RUN_ID, SAMPLE_DATASETS, SAMPLE_RUN, TOMLI

LIVE_TASKS = SAMPLE_DATASETS / "gauntlet-mini-live" / "tasks.jsonl"
REJECTIONS = [
    {"instance_id": "a__b-1", "stage": "validate", "reason": "no f2p"},
    {"instance_id": "a__b-2", "stage": "validate", "reason": "no f2p"},
    {"instance_id": "a__b-3", "stage": "leak", "reason": "statement"},
]
PRS = ["{}", "{}", "{}", "{}"]


def _workspace(tmp_path):
    ws = tmp_path / "work"
    made = ws / "tasks" / "fresh"
    made.mkdir(parents=True)
    shutil.copy(LIVE_TASKS, made / "tasks.jsonl")
    (made / "rejected.jsonl").write_text("".join(json.dumps(r) + "\n" for r in REJECTIONS) + "not json\n")
    (made / "prs.jsonl").write_text("\n".join(PRS) + "\n")
    shutil.copytree(SAMPLE_RUN, ws / "runs" / "mine")
    return ws


def test_workspace_task_sets_and_runs_load_with_their_own_ids(tmp_path):
    store = Store.load(None, (), _workspace(tmp_path))
    datasets = {d.id: d for d in store.datasets()}
    fresh = datasets["workspace/fresh"]
    assert fresh.from_workspace and "workspace" in fresh.title and fresh.tasks > 0
    detail = store.dataset("workspace/fresh")
    assert detail.prs_collected == len(PRS)
    assert {f.id: f.count for f in detail.rejected_by_stage} == Counter(r["stage"] for r in REJECTIONS)
    runs = {r.id: r for r in store.runs()}
    mine = runs["workspace/mine"]
    assert mine.from_workspace and mine.kind == "folder" and mine.dataset_id == "workspace/fresh"
    assert store.task(TOMLI).row.dataset_id == "workspace/fresh"
    assert any("isn't a rejection" in w for w in store.overview().warnings)


def test_shipped_data_comes_first_and_is_not_marked(tmp_path):
    store = Store.load(SAMPLE_DATASETS, [SAMPLE_RUN], _workspace(tmp_path))
    datasets = {d.id: d for d in store.datasets()}
    assert not datasets[LIVE_ID].from_workspace
    assert store.task(TOMLI).row.dataset_id == LIVE_ID
    assert datasets["workspace/fresh"].tasks == 0
    runs = {r.id: r for r in store.runs()}
    assert not runs[RUN_ID].from_workspace and runs["workspace/mine"].from_workspace
    assert any("already loaded" in w for w in store.overview().warnings)


def test_half_written_folders_are_skipped_with_a_warning(tmp_path):
    ws = tmp_path / "work"
    collecting = ws / "tasks" / "collecting"
    collecting.mkdir(parents=True)
    (collecting / "prs.jsonl").write_text("{}\n")
    (ws / "tasks" / "empty").mkdir()
    (ws / "runs" / "starting" / "trajectories").mkdir(parents=True)
    partial = ws / "runs" / "partial"
    shutil.copytree(SAMPLE_RUN, partial)
    results = partial / "results.jsonl"
    results.write_text(results.read_text() + '{"episode_id": "cut off mid')
    store = Store.load(None, (), ws)
    warnings = store.overview().warnings
    assert any("collecting" in w and "still" in w for w in warnings)
    assert any("starting" in w for w in warnings)
    assert not any("empty" in w for w in warnings)
    assert [d.id for d in store.datasets()] == []
    assert [r.id for r in store.runs()] == ["workspace/partial"]


def test_a_missing_workspace_loads_nothing(tmp_path):
    store = Store.load(None, (), tmp_path / "nothing")
    assert store.datasets() == () and store.runs() == () and store.overview().warnings == ()


def test_reload_sees_a_new_run(tmp_path):
    ws = _workspace(tmp_path)
    store = Store.load(SAMPLE_DATASETS, [SAMPLE_RUN], ws)
    shutil.copytree(SAMPLE_RUN, ws / "runs" / "later")
    again = store.reload()
    assert again is not store
    assert "workspace/later" in {r.id for r in again.runs()}
    assert "workspace/later" not in {r.id for r in store.runs()}
    assert {d.id for d in again.datasets()} == {d.id for d in store.datasets()}


def test_reload_without_a_workspace_keeps_the_old_arguments():
    store = Store.load(SAMPLE_DATASETS, [SAMPLE_RUN])
    assert {r.id for r in store.reload().runs()} == {r.id for r in store.runs()}
