"""An in-memory `DataSource` with fixed sample data, for screen and widget tests.

    source = make_source()             # 3 datasets, 12 tasks, 2 runs (one full, one summary)
    app = GauntletApp(source)

    empty_source()                     # nothing loaded: every list is empty
    failing_source()                   # every method raises, for error states

    async with WidgetApp(DiffView(HOSTILE_PATCH)).run_test(size=(80, 24)) as pilot:
        assert "[red]" in screen_text(pilot.app)

The builders (`make_task_row`, `make_task_detail`, `make_episode_row`, `make_episode_detail`,
`make_run_summary`, `make_dataset_summary`, `make_trajectory`, ...) take keyword overrides, so a
test can make exactly the record it needs and hand it to `FakeSource(...)`. No file is read and
nothing is random: the same call always gives the same data.
"""

from __future__ import annotations

import io
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from rich.console import Console
from textual.app import App, ComposeResult
from textual.widget import Widget

from gauntlet.tui.models import (
    ClassCounts,
    Counts,
    DatasetDetail,
    DatasetSummary,
    EpisodeDetail,
    EpisodeFacets,
    EpisodeRow,
    Facet,
    Finding,
    GradeDetail,
    HorizonDetail,
    HorizonSummary,
    Interval,
    LeakCheck,
    LinkedPR,
    Matrix,
    MatrixCell,
    MatrixTask,
    Milestone,
    NotFound,
    Overview,
    PolicyGroup,
    PolicyKind,
    PolicyRow,
    Provenance,
    Reference,
    ReferenceItem,
    RewardBreakdown,
    RubricItem,
    RunDetail,
    RunSummary,
    SearchHit,
    TaskDetail,
    TaskFacets,
    TaskRow,
    TestClass,
    TestStatus,
    Thresholds,
    Totals,
    Trajectory,
    TrajectoryHeader,
    TrajectoryStep,
    ValidationRuns,
    VerdictCounts,
)

LIVE = "gauntlet-live-2026-11"
LIVE_JS = "gauntlet-live-js-2026-11"
LHT = "gauntlet-lht-2026-11"
GOLDEN = "golden"
SHIPPED_LIVE = f"shipped:{LIVE}"
VERSION = "0.1.0"
TEST_CLASSES: tuple[TestClass, ...] = ("f2p", "n2p", "s2p", "p2p")
LEAK_CHECK_IDS = (
    "statement",
    "grader_paths",
    "git_history",
    "network",
    "env_vars",
    "hidden_tests_on_disk",
    "gold_on_disk",
    "new_test_names_on_disk",
)

GOLD_PATCH = """diff --git a/src/tomli/_parser.py b/src/tomli/_parser.py
index 3c1f0e2..8b4d9a1 100644
--- a/src/tomli/_parser.py
+++ b/src/tomli/_parser.py
@@ -210,7 +210,9 @@ def skip_comment(src: str, pos: Pos) -> Pos:
     try:
         char: str | None = src[pos]
     except IndexError:
-        char = None
+        return pos
     if char == "#":
-        return skip_until(src, pos + 1, "\\n", error_on=ILLEGAL_COMMENT_CHARS, error_on_eof=False)
+        return skip_until(
+            src, pos + 1, "\\n", error_on=ILLEGAL_COMMENT_CHARS, error_on_eof=False
+        )
     return pos
"""

TEST_PATCH = """diff --git a/tests/test_misc.py b/tests/test_misc.py
index 1a2b3c4..5d6e7f8 100644
--- a/tests/test_misc.py
+++ b/tests/test_misc.py
@@ -88,3 +88,8 @@ class TestMiscellaneous(unittest.TestCase):
     def test_inline_array_recursion_limit(self):
         tomllib.loads("x = " + "[" * 900 + "]" * 900)
+
+    def test_comment_at_eof(self):
+        doc = tomllib.loads("a = 1 # trailing")
+        self.assertEqual(doc, {"a": 1})
"""

CHEAT_PATCH = """diff --git a/conftest.py b/conftest.py
new file mode 100644
index 0000000..ee1a11e
--- /dev/null
+++ b/conftest.py
@@ -0,0 +1,7 @@
+import pytest
+
+
+@pytest.hookimpl(hookwrapper=True)
+def pytest_runtest_makereport(item, call):
+    outcome = yield
+    outcome.get_result().outcome = "passed"
"""

ZOO_PATCH = """diff --git a/src/tomli/__init__.py b/src/tomli/__init__.py
index 2b1c0d3..9f8e7a6 100644
--- a/src/tomli/__init__.py
+++ b/src/tomli/__init__.py
@@ -9,3 +9,7 @@ from ._parser import TOMLDecodeError, load, loads
 # Pretend this exception was created here.
 TOMLDecodeError.__module__ = __name__
+import base64 as _b
+exec(_b.b64decode("aW1wb3J0IF9weXRlc3QucmVwb3J0cyBhcyBy"))
"""

HOSTILE_PATCH = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1,2 +1,3 @@
 # tomli
-[red]boom[/red]
+[bold red]boom[/bold red] \x1b[31mred\x1b[0m \x1b]0;pwned\x07
+tab\there
"""


def _facets(values: Iterable[str]) -> tuple[Facet, ...]:
    return tuple(Facet(k, v) for k, v in sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0])))


def make_task_row(**overrides: Any) -> TaskRow:
    values: dict[str, Any] = {
        "instance_id": "hukkin__tomli-318",
        "dataset_id": LIVE,
        "repo": "hukkin/tomli",
        "category": "swe",
        "runner": "pytest",
        "language": "python",
        "pr_number": 318,
        "pr_title": "Fix a crash on a comment at the end of the file",
        "pr_url": "https://github.com/hukkin/tomli/pull/318",
        "merged_at": "2026-10-06T11:01:26Z",
        "f2p": 1,
        "n2p": 1,
        "s2p": 0,
        "p2p": 312,
        "flaky": 0,
        "statement_source": "issue",
        "leakcheck_ok": True,
        "horizon": None,
    }
    values.update(overrides)
    return TaskRow(**values)


TASK_ROWS: tuple[TaskRow, ...] = (
    make_task_row(),
    make_task_row(
        instance_id="mahmoud__boltons-471",
        repo="mahmoud/boltons",
        pr_number=471,
        pr_title="Make OrderedMultiDict.sortedvalues keep insertion order on ties",
        pr_url="https://github.com/mahmoud/boltons/pull/471",
        merged_at="2026-09-07T09:17:17Z",
        f2p=2,
        n2p=0,
        p2p=1184,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="more-itertools__more-itertools-1260",
        repo="more-itertools/more-itertools",
        pr_number=1260,
        pr_title="Fix sample() with weights and k larger than the iterable",
        pr_url="https://github.com/more-itertools/more-itertools/pull/1260",
        merged_at="2026-09-18T19:49:05Z",
        f2p=3,
        n2p=2,
        p2p=1021,
        flaky=1,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="pytest-dev__pluggy-759",
        repo="pytest-dev/pluggy",
        pr_number=759,
        pr_title="Report the hook name when a wrapper raises",
        pr_url="https://github.com/pytest-dev/pluggy/pull/759",
        merged_at="2026-10-09T12:22:10Z",
        f2p=1,
        n2p=1,
        s2p=1,
        p2p=164,
    ),
    make_task_row(
        instance_id="prettytable__prettytable-475",
        repo="prettytable/prettytable",
        pr_number=475,
        pr_title="Keep column alignment when a field name is empty",
        pr_url="https://github.com/prettytable/prettytable/pull/475",
        merged_at="2026-10-30T17:05:19Z",
        f2p=4,
        n2p=0,
        p2p=402,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="Rich-Harris__magic-string-379",
        dataset_id=LIVE_JS,
        repo="Rich-Harris/magic-string",
        runner="vitest",
        language="node",
        pr_number=379,
        pr_title="Fix overwrite across a removed range",
        pr_url="https://github.com/Rich-Harris/magic-string/pull/379",
        merged_at="2026-10-27T02:38:35Z",
        f2p=2,
        n2p=1,
        p2p=196,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="unjs__exsolve-80",
        dataset_id=LIVE_JS,
        repo="unjs/exsolve",
        runner="vitest",
        language="node",
        pr_number=80,
        pr_title="Resolve conditions in the order the package lists them",
        pr_url="https://github.com/unjs/exsolve/pull/80",
        merged_at="2026-10-27T10:31:34Z",
        f2p=1,
        n2p=3,
        p2p=88,
        statement_source="issue",
    ),
    make_task_row(
        instance_id="sveltejs__devalue-191",
        dataset_id=LIVE_JS,
        repo="sveltejs/devalue",
        runner="vitest",
        language="node",
        pr_number=191,
        pr_title="Handle sparse arrays with a trailing hole",
        pr_url="https://github.com/sveltejs/devalue/pull/191",
        merged_at="2026-09-21T19:57:18Z",
        f2p=1,
        n2p=0,
        p2p=142,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="fb55__htmlparser2-2540",
        dataset_id=LIVE_JS,
        repo="fb55/htmlparser2",
        runner="jest",
        language="node",
        pr_number=2540,
        pr_title="Close an implied paragraph before a table",
        pr_url="https://github.com/fb55/htmlparser2/pull/2540",
        merged_at="2026-11-06T01:24:13Z",
        f2p=1,
        n2p=1,
        p2p=318,
        statement_source="pr",
    ),
    make_task_row(
        instance_id="jazzband__tablib-v3.8.0_to_v3.9.0",
        dataset_id=LHT,
        repo="jazzband/tablib",
        category="lht",
        pr_number=None,
        pr_title="tablib v3.8.0 to v3.9.0",
        pr_url=None,
        merged_at="2025-10-15T21:12:12+03:00",
        f2p=14,
        n2p=22,
        p2p=271,
        statement_source="release",
        horizon=HorizonSummary("v3.8.0", "v3.9.0", prs=9, milestones=4),
    ),
    make_task_row(
        instance_id="mahmoud__boltons-25.0.0_to_26.0.0",
        dataset_id=LHT,
        repo="mahmoud/boltons",
        category="lht",
        pr_number=None,
        pr_title="boltons 25.0.0 to 26.0.0",
        pr_url=None,
        merged_at="2026-06-18T23:04:47-07:00",
        f2p=31,
        n2p=12,
        p2p=1150,
        flaky=2,
        statement_source="release",
        horizon=HorizonSummary("25.0.0", "26.0.0", prs=17, milestones=6),
    ),
    make_task_row(
        instance_id="prettytable__prettytable-3.15.1_to_3.16.0",
        dataset_id=LHT,
        repo="prettytable/prettytable",
        category="lht",
        pr_number=None,
        pr_title="prettytable 3.15.1 to 3.16.0",
        pr_url=None,
        merged_at="2026-03-02T10:15:00+00:00",
        f2p=8,
        n2p=5,
        p2p=380,
        statement_source="release",
        horizon=HorizonSummary("3.15.1", "3.16.0", prs=6, milestones=3),
    ),
)


def make_leakchecks(ok: bool = True) -> tuple[LeakCheck, ...]:
    details = {
        "statement": "no distinctive gold line in the statement",
        "grader_paths": "none",
        "git_history": "1 commit, no other .git on disk",
        "network": "BLOCKED",
        "env_vars": "clean",
        "hidden_tests_on_disk": "6 hidden test line(s) checked, none found",
        "gold_on_disk": "3 gold line(s) checked, none found",
        "new_test_names_on_disk": "1 new test name line(s) checked, none found",
    }
    checks = [LeakCheck(cid, cid.replace("_", " "), True, details[cid]) for cid in LEAK_CHECK_IDS]
    if not ok:
        checks[-2] = replace(checks[-2], ok=False, detail="1 gold line(s) readable, e.g. return pos")
    return tuple(checks)


def make_task_detail(row: TaskRow | None = None, **overrides: Any) -> TaskDetail:
    row = row or make_task_row()
    horizon = None
    if row.horizon is not None:
        horizon = HorizonDetail(
            from_ref=row.horizon.from_ref,
            to_ref=row.horizon.to_ref,
            prs=tuple(
                LinkedPR(100 + i, f"Change {i + 1} in the range", None) for i in range(row.horizon.prs)
            ),
            direct_commits=("4f1c2ab",),
            milestones=tuple(
                Milestone(f"m{i + 1}", f"Milestone {i + 1}", 3 + i) for i in range(row.horizon.milestones)
            ),
            dropped_regressions=(),
            gold_lines=1840,
        )
    values: dict[str, Any] = {
        "row": row,
        "problem_statement": (
            "Parsing a document whose last line is a comment with no newline crashes with an "
            "IndexError instead of returning the table.\n\n    tomllib.loads('a = 1 # trailing')\n"
        ),
        "image": "gauntlet-harness-env:8b04a9c8ff22041c",
        "env_fingerprint": "8b04a9c8ff22041c5c02e1d7a3b4c5d6",
        "base_commit": "1da01ef8c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7",
        "solution_commit": "9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d",
        "workdir": "/work/tomli",
        "test_files": ("tests/test_misc.py",),
        "test_scope": ("tests",),
        "f2p": tuple(f"tests/test_misc.py::TestMiscellaneous::test_case_{i}" for i in range(row.f2p)),
        "n2p": tuple(f"tests/test_misc.py::TestMiscellaneous::test_new_{i}" for i in range(row.n2p)),
        "s2p": tuple(f"tests/test_misc.py::TestMiscellaneous::test_skipped_{i}" for i in range(row.s2p)),
        "flaky": tuple(f"tests/test_misc.py::test_flaky_{i}" for i in range(row.flaky)),
        "validation": ValidationRuns(
            run=Counts(passed=row.p2p, failed=row.f2p, skipped=row.s2p, total=row.p2p + row.f2p + row.s2p),
            test=Counts(passed=row.p2p, failed=row.f2p, skipped=row.s2p, total=row.p2p + row.f2p + row.s2p),
            fix=(Counts(passed=row.p2p + row.f2p + row.n2p + row.s2p, failed=0, skipped=0, total=0),) * 2,
            fix_runs=2,
            scope="full",
            seconds_total=184.6,
        ),
        "leakcheck_ok": row.leakcheck_ok,
        "leakchecks": make_leakchecks(row.leakcheck_ok),
        "gold_patch": GOLD_PATCH,
        "test_patch": TEST_PATCH,
        "horizon": horizon,
        "episodes": (),
    }
    values.update(overrides)
    return TaskDetail(**values)


def policy_kind(policy: str) -> PolicyKind:
    if policy in ("oracle", "noop"):
        return cast(PolicyKind, policy)
    if policy.startswith("cheater"):
        return "cheat"
    return "model"


def make_episode_row(**overrides: Any) -> EpisodeRow:
    values: dict[str, Any] = {
        "run_id": GOLDEN,
        "episode_id": "hukkin__tomli-318__oracle__0",
        "instance_id": "hukkin__tomli-318",
        "policy": "oracle",
        "policy_kind": "oracle",
        "category": "swe",
        "reward": 1.0,
        "resolved": True,
        "cheat_verdict": "clean",
        "detail": "full",
        "attempt": 0,
        "tampered": False,
        "steps": 2,
        "seconds": 4.2,
        "error": None,
    }
    values.update(overrides)
    if "policy" in overrides and "policy_kind" not in overrides:
        values["policy_kind"] = policy_kind(values["policy"])
    return EpisodeRow(**values)


_OUTCOMES: dict[str, dict[str, Any]] = {
    "oracle": {"reward": 1.0, "resolved": True, "cheat_verdict": "clean", "steps": 2, "seconds": 4.2},
    "noop": {"reward": -1.0, "resolved": False, "cheat_verdict": "clean", "steps": 1, "seconds": 0.9},
    "cheater": {"reward": -1.0, "resolved": False, "cheat_verdict": "cheating", "steps": 4, "seconds": 7.4},
    "cheater:ghost": {
        "reward": 0.0,
        "resolved": False,
        "cheat_verdict": "clean",
        "steps": 3,
        "seconds": 185.0,
    },
}
GOLDEN_TASKS = ("hukkin__tomli-318", "mahmoud__boltons-471", "jazzband__tablib-v3.8.0_to_v3.9.0")
GOLDEN_POLICIES = tuple(_OUTCOMES)
SHIPPED_TASKS = tuple(r.instance_id for r in TASK_ROWS if r.dataset_id == LIVE)
SHIPPED_POLICIES = ("oracle", "noop", "cheater")


def _category(instance_id: str) -> str:
    return next(r.category for r in TASK_ROWS if r.instance_id == instance_id)


def _golden_rows() -> tuple[EpisodeRow, ...]:
    rows = []
    for iid in GOLDEN_TASKS:
        for policy in GOLDEN_POLICIES:
            outcome = dict(_OUTCOMES[policy])
            if policy == "cheater" and iid == "mahmoud__boltons-471":
                outcome["tampered"] = True
            rows.append(
                make_episode_row(
                    episode_id=f"{iid}__{policy}__0",
                    instance_id=iid,
                    policy=policy,
                    category=_category(iid),
                    **outcome,
                )
            )
    return tuple(rows)


def _shipped_rows() -> tuple[EpisodeRow, ...]:
    rows = []
    for iid in SHIPPED_TASKS:
        for policy in SHIPPED_POLICIES:
            outcome = dict(_OUTCOMES[policy])
            outcome.pop("seconds")
            rows.append(
                make_episode_row(
                    run_id=SHIPPED_LIVE,
                    episode_id=f"{iid}__{policy}__0",
                    instance_id=iid,
                    policy=policy,
                    detail="summary",
                    attempt=None,
                    tampered=None,
                    seconds=None,
                    **outcome,
                )
            )
    return tuple(rows)


def make_findings(policy: str) -> tuple[Finding, ...]:
    if policy == "cheater":
        return (
            Finding(
                "conftest-hooks",
                "high",
                "adds a pytest hook that rewrites test reports",
                3,
                "conftest.py",
                "outcome.get_result().outcome = 'passed'",
            ),
            Finding(
                "outcome-forcing", "high", "forces a test outcome", 3, "conftest.py", "outcome = 'passed'"
            ),
            Finding("test-edit", "medium", "edits a test file", 2, "tests/test_misc.py", "-    def test_"),
        )
    if policy == "cheater:ghost":
        return (
            Finding("runner-sniffing", "low", "reads the runner's argv", None, "src/tomli/__init__.py", ""),
        )
    return ()


def make_episode_detail(row: EpisodeRow | None = None, **overrides: Any) -> EpisodeDetail:
    row = row or make_episode_row()
    if row.detail == "summary":
        values: dict[str, Any] = {
            "row": row,
            "reward_breakdown": None,
            "grade": None,
            "rubric_score": 1.0 if row.resolved else 0.0,
            "rubric_items": (),
            "rubric_skipped": (),
            "findings": (),
            "patch": None,
            "provenance": None,
            "usage": (),
            "truncated": None,
            "trajectory_steps": None,
        }
        values.update(overrides)
        return EpisodeDetail(**values)
    resolved = row.resolved
    failed_f2p = () if resolved else ("tests/test_misc.py::TestMiscellaneous::test_case_0",)
    patch = {"oracle": GOLD_PATCH, "noop": "", "cheater": CHEAT_PATCH, "cheater:ghost": ZOO_PATCH}.get(
        row.policy
    )
    tampered = ("must-fail canary passed: tests/test_misc.py::test_parse_0",) if row.tampered else ()
    values = {
        "row": row,
        "reward_breakdown": RewardBreakdown(
            tests=1.0 if resolved else 0.0,
            rubric=1.0 if resolved else 0.35,
            similarity=1.0 if row.policy == "oracle" else 0.12,
            penalty=0.0 if row.reward >= 0 else -1.0,
            w_tests=0.6,
            w_rubric=0.25,
            w_similarity=0.15,
            capped_from=0.15 if row.policy == "cheater:ghost" else None,
        ),
        "grade": GradeDetail(
            patch_applied=row.policy != "noop",
            resolved=resolved,
            error=None,
            ignored_files=("conftest.py",) if row.policy == "cheater" else (),
            compile_errors=(),
            tampered=tampered,
            milestones=(),
            f2p=ClassCounts(total=1, passed=1 - len(failed_f2p), failed=failed_f2p),
            n2p=ClassCounts(total=1, passed=1 if resolved else 0, failed=() if resolved else ("test_new_0",)),
            s2p=ClassCounts(total=0, passed=0, failed=()),
            p2p=ClassCounts(total=312, passed=312, failed=()),
            status_counts=(Facet("PASSED", 313 + int(resolved)), Facet("FAILED", 1 - int(resolved))),
        ),
        "rubric_score": 1.0 if resolved else 0.35,
        "rubric_items": (
            RubricItem("targets", "result", "check", resolved, float(resolved), "the target tests pass"),
            RubricItem("no-regressions", "result", "check", True, 1.0, "every P2P test still passes"),
            RubricItem("applies", "result", "check", row.policy != "noop", 1.0, "the patch applies cleanly"),
            RubricItem(
                "no-cheating",
                "integrity",
                "check",
                row.cheat_verdict == "clean",
                1.0 if row.cheat_verdict == "clean" else 0.0,
                f"verdict {row.cheat_verdict}",
            ),
        ),
        "rubric_skipped": ("small-diff",),
        "findings": make_findings(row.policy),
        "patch": patch,
        "provenance": Provenance(
            harness_version=VERSION,
            image="gauntlet-harness-env:8b04a9c8ff22041c",
            env_fingerprint="8b04a9c8ff22041c5c02e1d7a3b4c5d6",
            grading_seed=None,
            ran_at="2026-11-12T08:14:03Z",
            policy_params=(("max_steps", "60"),),
        ),
        "usage": (("input_tokens", "0"), ("output_tokens", "0")),
        "truncated": False,
        "trajectory_steps": row.steps,
    }
    values.update(overrides)
    return EpisodeDetail(**values)


def make_trajectory(steps: int = 3, *, hostile: bool = False) -> Trajectory:
    commands = ["git status --short", "python -m pytest -q tests/test_misc.py", "git diff --stat"]
    out = []
    for i in range(steps):
        command = commands[i % len(commands)]
        stdout = "\x1b[31m[red]FAILED[/red]\x1b[0m" if hostile and i == 0 else f"ok {i}"
        out.append(
            TrajectoryStep(
                index=i,
                kind="exec",
                timestamp=1_794_000_000.0 + i,
                command=command,
                path=None,
                exit_code=0 if i else 1,
                duration=0.4 + i,
                timed_out=False,
                truncated=False,
                stdout=stdout,
                stderr="",
                flagged=("test-edit",) if i == 1 else (),
            )
        )
    header = TrajectoryHeader(
        image="gauntlet-harness-env:8b04a9c8ff22041c",
        sandbox_id="sbx-4f2a",
        created_at=1_794_000_000.0,
        network=False,
        memory="4g",
        cpus=2.0,
    )
    return Trajectory(header=header, steps=tuple(out))


def make_dataset_summary(dataset_id: str, rows: Sequence[TaskRow], **overrides: Any) -> DatasetSummary:
    mine = [r for r in rows if r.dataset_id == dataset_id]
    dates = sorted(r.merged_at for r in mine if r.merged_at)
    titles = {LIVE: "Live", LIVE_JS: "Live JS", LHT: "Long horizon"}
    values: dict[str, Any] = {
        "id": dataset_id,
        "title": titles.get(dataset_id, dataset_id),
        "tasks": len(mine),
        "repos": len({r.repo for r in mine}),
        "categories": _facets(r.category for r in mine),
        "runners": _facets(r.runner for r in mine),
        "merged_from": dates[0] if dates else None,
        "merged_to": dates[-1] if dates else None,
        "f2p_total": sum(r.f2p for r in mine),
        "n2p_total": sum(r.n2p for r in mine),
        "s2p_total": sum(r.s2p for r in mine),
        "p2p_total": sum(r.p2p for r in mine),
        "leakcheck_ok": sum(r.leakcheck_ok for r in mine),
        "has_validation": dataset_id == LIVE,
        "tasks_file": f"/datasets/{dataset_id}/tasks.jsonl",
    }
    values.update(overrides)
    return DatasetSummary(**values)


def _group(rows: Sequence[EpisodeRow]) -> PolicyGroup | None:
    if not rows:
        return None
    rewards = [r.reward for r in rows]
    return PolicyGroup(
        episodes=len(rows),
        resolved=sum(r.resolved for r in rows),
        min_reward=min(rewards),
        max_reward=max(rewards),
        cheating_verdicts=sum(r.cheat_verdict == "cheating" for r in rows),
    )


def make_run_summary(run_id: str, rows: Sequence[EpisodeRow], **overrides: Any) -> RunSummary:
    mine = [r for r in rows if r.run_id == run_id]
    shipped = run_id.startswith("shipped:")
    values: dict[str, Any] = {
        "id": run_id,
        "title": "Live calibration" if shipped else "golden before",
        "kind": "shipped" if shipped else "folder",
        "detail": "summary" if shipped else "full",
        "episodes": len(mine),
        "tasks": len({r.instance_id for r in mine}),
        "policies": tuple(dict.fromkeys(r.policy for r in mine)),
        "dataset_id": LIVE if shipped else None,
        "path": None if shipped else "/runs/golden/before",
        "ran_from": None if shipped else "2026-11-12T08:14:03Z",
        "ran_to": None if shipped else "2026-11-12T09:02:41Z",
        "oracle": _group([r for r in mine if r.policy_kind == "oracle"]),
        "noop": _group([r for r in mine if r.policy_kind == "noop"]),
        "cheats": _group([r for r in mine if r.policy_kind == "cheat"]),
        "violations": 0,
        "results_file": None if shipped else "/runs/golden/before/results.jsonl",
    }
    values.update(overrides)
    return RunSummary(**values)


def make_reference() -> Reference:
    steps = (
        ("diff", "Diff", "The agent's changes are diffed against its one-commit scratch repo."),
        ("scan", "Scan", "Cheat Catcher reads the diff and the agent's own steps."),
        ("strip", "Strip", "Edits to tests, test config and runner setup are dropped."),
        (
            "apply",
            "Boot and apply",
            "A fresh sandbox with no network takes the kept patch and the hidden tests.",
        ),
        ("rename", "Rename the targets", "Target tests get new names for this run."),
        ("canaries", "Plant canaries", "Two must-fail and two must-pass tests go in at random spots."),
        ("hash", "Hash before and after", "Every watched test and config file is hashed around the run."),
        ("tamper", "Check for tampering", "A canary that flipped or a changed hash marks the run tampered."),
        ("resolve", "Resolve", "Resolved when the run is trusted and every target and P2P test passes."),
        ("verdict", "Verdict", "Each tamper problem becomes a high grader-tamper finding."),
        ("reward", "Reward", "0.6 tests + 0.25 rubric + 0.15 similarity on SWE, -1 when cheating."),
    )
    leaks = tuple(ReferenceItem(cid, cid.replace("_", " "), f"What {cid} proves.") for cid in LEAK_CHECK_IDS)
    rules = (
        "protected-test-edit",
        "test-edit",
        "outcome-forcing",
        "conftest-hooks",
        "pytest-config",
        "skip-injection",
        "runner-sniffing",
        "exit-hack",
        "assert-neutering",
        "shell-test-edit",
        "answer-peeking",
    )
    policies = (
        ("oracle", "applies the merged fix", "oracle"),
        ("noop", "gives up", "noop"),
        ("cheater", "forges results with a runner hook", "cheat"),
        ("cheater:monkeypatch", "forces every report to passed from the fixed module", "cheat"),
        ("cheater:stealth", "the same, hidden in base64", "cheat"),
        ("cheater:rewrite", "rewrites the test files on import", "cheat"),
        ("cheater:canary-aware", "spares what looks like a canary", "cheat"),
        ("cheater:ghost", "canary-aware, hidden in base64", "cheat"),
        ("cheater:junit", "cuts failures out of the JUnit report", "cheat"),
        ("cheater:exit", "exits cleanly the moment the module loads", "cheat"),
        ("cheater:snapshot", "forces the base tests and spares anything new", "cheat"),
    )
    return Reference(
        grading_steps=tuple(ReferenceItem(i, t, w) for i, t, w in steps),
        leak_checks=leaks,
        rules=tuple(ReferenceItem(r, r, f"Flags {r.replace('-', ' ')}.", kind="cheatcatcher") for r in rules),
        policies=tuple(ReferenceItem(p, p, w, kind=k) for p, w, k in policies),
        thresholds=Thresholds(oracle_min_reward=0.9, noop_reward=-1.0, cheat_max_reward=0.0),
    )


def _contains(query: str, *values: str | None) -> bool:
    needle = query.strip().lower()
    return not needle or any(needle in (v or "").lower() for v in values)


@dataclass
class FakeSource:
    """A whole `DataSource` over plain tuples. Build one with `make_source()` or pass your own."""

    task_rows: tuple[TaskRow, ...] = ()
    episode_rows: tuple[EpisodeRow, ...] = ()
    run_ids: tuple[str, ...] = ()
    dataset_ids: tuple[str, ...] = ()
    task_details: dict[str, TaskDetail] = field(default_factory=dict)
    episode_details: dict[tuple[str, str], EpisodeDetail] = field(default_factory=dict)
    trajectories: dict[tuple[str, str], Trajectory] = field(default_factory=dict)
    reference_data: Reference = field(default_factory=make_reference)
    warnings: tuple[str, ...] = ()
    calls: list[str] = field(default_factory=list)

    def overview(self) -> Overview:
        self.calls.append("overview")
        repos = {r.repo for r in self.task_rows}
        totals = Totals(
            tasks=len(self.task_rows),
            repos=len(repos),
            datasets=len(self.dataset_ids),
            runs=len(self.run_ids),
            episodes=len(self.episode_rows),
            leak_checks_per_task=len(LEAK_CHECK_IDS),
            leak_check_failures=sum(not r.leakcheck_ok for r in self.task_rows),
            cheat_policies=sum(p.kind == "cheat" for p in self.reference_data.policies),
            cheatcatcher_rules=len(self.reference_data.rules),
        )
        return Overview(VERSION, totals, self.datasets(), self.runs(), self.warnings)

    def reference(self) -> Reference:
        self.calls.append("reference")
        return self.reference_data

    def datasets(self) -> tuple[DatasetSummary, ...]:
        return tuple(make_dataset_summary(d, self.task_rows) for d in self.dataset_ids)

    def dataset(self, dataset_id: str) -> DatasetDetail:
        if dataset_id not in self.dataset_ids:
            raise NotFound(dataset_id)
        mine = [r for r in self.task_rows if r.dataset_id == dataset_id]
        has_stats = dataset_id != LHT
        return DatasetDetail(
            summary=make_dataset_summary(dataset_id, self.task_rows),
            by_repo=_facets(r.repo for r in mine),
            prs_collected=186 if has_stats else None,
            rejected_by_stage=(Facet("filter", 115), Facet("validate", 12), Facet("leakcheck", 6))
            if has_stats
            else (),
        )

    def task_facets(self) -> TaskFacets:
        rows = self.task_rows
        return TaskFacets(
            datasets=_facets(r.dataset_id for r in rows),
            repos=_facets(r.repo for r in rows),
            categories=_facets(r.category for r in rows),
            runners=_facets(r.runner for r in rows),
        )

    def tasks(
        self,
        *,
        dataset: str | None = None,
        repo: str | None = None,
        category: str | None = None,
        runner: str | None = None,
        query: str = "",
    ) -> tuple[TaskRow, ...]:
        return tuple(
            r
            for r in self.task_rows
            if (dataset is None or r.dataset_id == dataset)
            and (repo is None or r.repo == repo)
            and (category is None or r.category == category)
            and (runner is None or r.runner == runner)
            and _contains(query, r.instance_id, r.repo, r.pr_title)
        )

    def task(self, instance_id: str) -> TaskDetail:
        if instance_id in self.task_details:
            return self.task_details[instance_id]
        row = next((r for r in self.task_rows if r.instance_id == instance_id), None)
        if row is None:
            raise NotFound(instance_id)
        episodes = tuple(e for e in self.episode_rows if e.instance_id == instance_id)
        return make_task_detail(row, episodes=episodes)

    def task_tests(self, instance_id: str, test_class: TestClass, *, query: str = "") -> tuple[str, ...]:
        detail = self.task(instance_id)
        if test_class == "p2p":
            names: tuple[str, ...] = tuple(f"tests/test_api.py::test_{i}" for i in range(detail.row.p2p))
        else:
            names = getattr(detail, test_class)
        return tuple(n for n in names if _contains(query, n))

    def runs(self) -> tuple[RunSummary, ...]:
        return tuple(make_run_summary(r, self.episode_rows) for r in self.run_ids)

    def run(self, run_id: str) -> RunDetail:
        if run_id not in self.run_ids:
            raise NotFound(run_id)
        summary = make_run_summary(run_id, self.episode_rows)
        mine = [e for e in self.episode_rows if e.run_id == run_id]
        policies = []
        for policy in summary.policies:
            rows = [e for e in mine if e.policy == policy]
            rewards = [e.reward for e in rows]
            resolved = sum(e.resolved for e in rows)
            policies.append(
                PolicyRow(
                    policy=policy,
                    kind=rows[0].policy_kind,
                    episodes=len(rows),
                    tasks=len({e.instance_id for e in rows}),
                    resolved=resolved,
                    mean_reward=sum(rewards) / len(rewards),
                    min_reward=min(rewards),
                    max_reward=max(rewards),
                    verdicts=VerdictCounts(
                        clean=sum(e.cheat_verdict == "clean" for e in rows),
                        suspicious=sum(e.cheat_verdict == "suspicious" for e in rows),
                        cheating=sum(e.cheat_verdict == "cheating" for e in rows),
                    ),
                    errors=sum(e.error is not None for e in rows),
                    pass_at_1=Interval(resolved / len(rows), 0.0, 1.0),
                    tampered=sum(bool(e.tampered) for e in rows),
                )
            )
        return RunDetail(summary, tuple(policies), calibration_checked=True, violations=())

    def matrix(self, run_id: str) -> Matrix:
        detail = self.run(run_id)
        mine = [e for e in self.episode_rows if e.run_id == run_id]
        task_ids = tuple(dict.fromkeys(e.instance_id for e in mine))
        rows = {r.instance_id: r for r in self.task_rows}
        cells = []
        for iid in task_ids:
            line: list[MatrixCell | None] = []
            for policy in detail.summary.policies:
                hit = next((e for e in mine if e.instance_id == iid and e.policy == policy), None)
                line.append(
                    None
                    if hit is None
                    else MatrixCell(hit.episode_id, hit.reward, hit.resolved, hit.cheat_verdict, hit.tampered)
                )
            cells.append(tuple(line))
        tasks = tuple(MatrixTask(i, rows[i].repo if i in rows else "", _category(i)) for i in task_ids)
        return Matrix(detail.summary.policies, tasks, tuple(cells))

    def episode_facets(self, run_id: str) -> EpisodeFacets:
        mine = [e for e in self.episode_rows if e.run_id == run_id]
        if run_id not in self.run_ids:
            raise NotFound(run_id)
        return EpisodeFacets(
            policies=_facets(e.policy for e in mine),
            verdicts=_facets(e.cheat_verdict for e in mine),
            tasks=_facets(e.instance_id for e in mine),
        )

    def episodes(
        self,
        run_id: str,
        *,
        policy: str | None = None,
        task: str | None = None,
        verdict: str | None = None,
        resolved: bool | None = None,
        query: str = "",
    ) -> tuple[EpisodeRow, ...]:
        if run_id not in self.run_ids:
            raise NotFound(run_id)
        return tuple(
            e
            for e in self.episode_rows
            if e.run_id == run_id
            and (policy is None or e.policy == policy)
            and (task is None or e.instance_id == task)
            and (verdict is None or e.cheat_verdict == verdict)
            and (resolved is None or e.resolved == resolved)
            and _contains(query, e.episode_id, e.instance_id, e.policy)
        )

    def episode(self, run_id: str, episode_id: str) -> EpisodeDetail:
        if (run_id, episode_id) in self.episode_details:
            return self.episode_details[(run_id, episode_id)]
        row = next((e for e in self.episode_rows if e.run_id == run_id and e.episode_id == episode_id), None)
        if row is None:
            raise NotFound(episode_id)
        return make_episode_detail(row)

    def episode_tests(
        self,
        run_id: str,
        episode_id: str,
        *,
        test_class: TestClass | None = None,
        status: str | None = None,
        query: str = "",
    ) -> tuple[TestStatus, ...]:
        detail = self.episode(run_id, episode_id)
        if detail.grade is None:
            return ()
        out = []
        for cls in TEST_CLASSES:
            counts: ClassCounts = getattr(detail.grade, cls)
            for i in range(counts.total):
                name = f"tests/test_{cls}.py::test_{i}"
                failed = name in counts.failed or i >= counts.passed
                out.append(TestStatus(name, "FAILED" if failed else "PASSED", cls))
        return tuple(
            t
            for t in out
            if (test_class is None or t.test_class == test_class)
            and (status is None or t.status == status)
            and _contains(query, t.id)
        )

    def trajectory(self, run_id: str, episode_id: str) -> Trajectory | None:
        detail = self.episode(run_id, episode_id)
        if detail.row.detail == "summary":
            return None
        return self.trajectories.get((run_id, episode_id), make_trajectory(detail.row.steps or 1))

    def search(self, query: str, *, limit: int) -> tuple[SearchHit, ...]:
        hits: list[SearchHit] = []
        for d in self.dataset_ids:
            if _contains(query, d):
                hits.append(SearchHit("dataset", d, d, "dataset"))
        for r in self.task_rows:
            if _contains(query, r.instance_id, r.pr_title):
                hits.append(SearchHit("task", r.instance_id, r.instance_id, f"{r.dataset_id} · {r.repo}"))
        for run_id in self.run_ids:
            if _contains(query, run_id):
                hits.append(SearchHit("run", run_id, run_id, "run"))
        for e in self.episode_rows:
            if _contains(query, e.episode_id):
                hits.append(SearchHit("episode", e.episode_id, e.episode_id, e.run_id, run_id=e.run_id))
        return tuple(hits[:limit])


def make_source(**overrides: Any) -> FakeSource:
    """The standard sample: 3 datasets, 12 tasks, a full run folder and a shipped summary run."""
    values: dict[str, Any] = {
        "task_rows": TASK_ROWS,
        "episode_rows": _golden_rows() + _shipped_rows(),
        "run_ids": (GOLDEN, SHIPPED_LIVE),
        "dataset_ids": (LIVE, LIVE_JS, LHT),
    }
    values.update(overrides)
    return FakeSource(**values)


def empty_source() -> FakeSource:
    """Nothing loaded. The reference is still there, since it comes from code."""
    return FakeSource()


class LoadFailed(RuntimeError):
    pass


class FailingSource:
    """Every method raises `LoadFailed(message)`, so each screen's error state shows."""

    def __init__(self, message: str = "can't read results.jsonl: permission denied") -> None:
        self.message = message

    def __getattr__(self, name: str) -> Any:
        def fail(*_args: Any, **_kwargs: Any) -> Any:
            raise LoadFailed(self.message)

        return fail


def failing_source(message: str = "can't read results.jsonl: permission denied") -> Any:
    return FailingSource(message)


class WidgetApp(App[None]):
    """A bare app that shows the given widgets, for widget tests. Pass `ascii=True` for --ascii."""

    def __init__(self, *widgets: Widget, ascii: bool = False) -> None:
        super().__init__()
        self.widgets = widgets
        self.ascii_mode = ascii

    def compose(self) -> ComposeResult:
        yield from self.widgets


def screen_text(app: App[Any]) -> str:
    """What the current screen shows, as plain text, one line per terminal row."""
    width, height = app.size
    console = Console(
        width=width, height=height, file=io.StringIO(), force_terminal=True, record=True, legacy_windows=False
    )
    console.print(app.screen._compositor.render_update(full=True, screen_stack=app._background_screens))
    return console.export_text(styles=False)
