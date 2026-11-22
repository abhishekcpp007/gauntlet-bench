from pathlib import Path

from gauntlet.harness.build import instance_id
from gauntlet.harness.lht import range_id
from gauntlet.harness.schema import PRInfo, Rejected
from gauntlet.tui import actions
from gauntlet.tui.widgets.buildfiles import (
    PR_UNIT,
    RANGE_UNIT,
    pr_instance_id,
    range_instance_id,
    read_build,
    read_rows,
)
from gauntlet.tui.workspace import Workspace

from .sample import SAMPLE_DATASETS, TOMLI

LIVE_TASKS = SAMPLE_DATASETS / "gauntlet-mini-live" / "tasks.jsonl"
LHT_TASKS = SAMPLE_DATASETS / "gauntlet-mini-lht" / "tasks.jsonl"


def pr(repo: str, number: int, title: str) -> PRInfo:
    return PRInfo(repo=repo, number=number, title=title, url=f"https://github.com/{repo}/pull/{number}")


def tomli_line() -> str:
    return next(line for line in LIVE_TASKS.read_text().splitlines() if f'"{TOMLI}"' in line)


def test_ids_match_the_harness():
    info = pr("hukkin/tomli", 318, "x")
    assert pr_instance_id(info.repo, info.number) == instance_id(info)
    for a, b in (("v1.2.0", "v1.3.0"), ("release/1.0", "1.1+build"), ("-rc1-", "2.0")):
        assert range_instance_id("pytest-dev/pluggy", a, b) == range_id("pytest-dev/pluggy", a, b)


def test_read_rows_skips_what_isnt_an_object(tmp_path: Path):
    path = tmp_path / "x.jsonl"
    path.write_text('{"a": 1}\n\nnot json\n[1, 2]\n{"b": 2}\n')
    rows, skipped = read_rows(path)
    assert rows == [{"a": 1}, {"b": 2}] and skipped == 2


def write_build(spec, *, prs, tasks, rejected) -> None:
    paths = {o.kind: Path(o.path) for o in spec.outputs}
    paths["tasks"].parent.mkdir(parents=True, exist_ok=True)
    if prs is not None:
        paths["prs"].write_text("".join(p.model_dump_json() + "\n" for p in prs))
    paths["tasks"].write_text("".join(line + "\n" for line in tasks))
    paths["rejected"].write_text("".join(r.model_dump_json() + "\n" for r in rejected))


def test_a_pr_build_names_each_pr_and_groups_rejections(tmp_path: Path):
    spec = actions.make_tasks(Workspace(tmp_path), ["hukkin/tomli"], name="t")
    prs = [
        pr("hukkin/tomli", 318, "Set smaller nesting"),
        pr("hukkin/tomli", 2, "Docs"),
        pr("hukkin/tomli", 3, "CI"),
    ]
    rejected = [
        Rejected(instance_id="hukkin__tomli-2", stage="filter", reason="no Python source changes"),
        Rejected(instance_id="hukkin__tomli-3", stage="filter", reason="no test module changes"),
    ]
    write_build(spec, prs=prs, tasks=[tomli_line()], rejected=rejected)
    summary = read_build(spec)
    assert summary.unit == PR_UNIT and summary.asked == len(prs) and summary.finished
    assert [(i.name, i.title) for i in summary.kept] == [("#318", "Set smaller nesting")]
    [(stage, items)] = summary.stages()
    assert stage == "filter" and [(i.name, i.title, i.reason) for i in items] == [
        ("#2", "Docs", "no Python source changes"),
        ("#3", "CI", "no test module changes"),
    ]


def test_several_repos_name_the_repo_and_the_biggest_group_comes_first(tmp_path: Path):
    spec = actions.make_tasks(Workspace(tmp_path), ["a/b", "c/d"], name="t")
    prs = [pr("a/b", 1, "one"), pr("c/d", 2, "two"), pr("c/d", 3, "three")]
    rejected = [
        Rejected(instance_id="a__b-1", stage="leak", reason="f2p_visible"),
        Rejected(instance_id="c__d-2", stage="runs", reason="boom"),
        Rejected(instance_id="c__d-3", stage="runs", reason="boom"),
    ]
    write_build(spec, prs=prs, tasks=[], rejected=rejected)
    summary = read_build(spec)
    assert [stage for stage, _ in summary.stages()] == ["runs", "leak"]
    assert summary.stages()[1][1][0].name == "a/b#1" and not summary.kept


def test_a_build_that_stopped_says_what_it_missed(tmp_path: Path):
    spec = actions.make_tasks(Workspace(tmp_path), ["a/b"], name="t")
    folder = Path(spec.outputs[0].path).parent
    folder.mkdir(parents=True)
    (folder / "prs.jsonl").write_text(pr("a/b", 1, "one").model_dump_json() + "\n" + "{broken\n")
    summary = read_build(spec)
    assert summary.missing == ("tasks.jsonl", "rejected.jsonl") and summary.skipped == 1
    assert summary.asked == 1 and not summary.finished


def test_a_range_build_names_each_range(tmp_path: Path):
    ranges = [actions.ReleaseRange("1.4.0", "1.5.0", 3, 0), actions.ReleaseRange("1.5.0", "1.6.0", 1, 0)]
    spec = actions.make_lht_tasks(Workspace(tmp_path), "pytest-dev/pluggy", ranges=ranges, name="l")
    lht_line = LHT_TASKS.read_text().splitlines()[0]
    rejected = [
        Rejected(
            instance_id=range_id("pytest-dev/pluggy", "1.5.0", "1.6.0"), stage="filter", reason="no source"
        )
    ]
    write_build(spec, prs=None, tasks=[lht_line], rejected=rejected)
    summary = read_build(spec)
    assert summary.unit == RANGE_UNIT and summary.asked == len(ranges)
    assert summary.kept[0].name.endswith("..1.5.0") and "PR" in summary.kept[0].title
    assert summary.rejected[0].name == "1.5.0..1.6.0" and summary.rejected[0].reason == "no source"
