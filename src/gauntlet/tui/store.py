"""`Store`: the viewer's read-only data layer over shipped datasets and run folders.

It parses tasks and episode rows up front and reads a trajectory, an RL record or a long test
list only when a screen asks for it. Every number comes from the harness's own code: `report`
and `stats` for pass rates and intervals, `cli.calibration_violations` for the calibration
check, `RULES` for Cheat Catcher. Nothing here imports Textual, prints, or writes a file.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from gauntlet.cheatcatcher import RULES
from gauntlet.harness import __version__
from gauntlet.harness.cli import CALIBRATION_POLICIES, calibration_violations, rotted_tasks
from gauntlet.harness.report import solved, summarize
from gauntlet.harness.runners import runner_for
from gauntlet.harness.schema import EpisodeResult, GradeResult, HarnessTask, Rejected, RubricScore, Status

from .models import (
    Category,
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
    HitKind,
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
    RunKind,
    RunSummary,
    SearchHit,
    Severity,
    TaskDetail,
    TaskFacets,
    TaskRow,
    TestClass,
    TestStatus,
    TestStatusName,
    Thresholds,
    Totals,
    Trajectory,
    TrajectoryHeader,
    TrajectoryStep,
    ValidationRuns,
    Verdict,
    VerdictCounts,
)
from .workspace import PRS_FILE, REJECTED_FILE, RUNS_DIR, TASKS_DIR

TASKS_FILE = "tasks.jsonl"
STATS_FILE = "stats.json"
VALIDATION_FILE = "validation.jsonl"
README_FILE = "README.md"
RESULTS_FILE = "results.jsonl"
TRAJECTORY_DIR = "trajectories"
RL_DIR = "rl"

DATASET_PREFIX = "gauntlet-"
SHIPPED_PREFIX = "shipped-"
WORKSPACE_PREFIX = "workspace/"
ORACLE = "oracle"
NOOP = "noop"
CHEAT_PREFIX = "cheater"

# A screen shows text, it doesn't need megabytes of it. Anything longer is cut here and the
# record says it was cut.
PATCH_LIMIT = 1_000_000
OUTPUT_LIMIT = 50_000

TEST_CLASSES: tuple[TestClass, ...] = ("f2p", "n2p", "s2p", "p2p")
STATUS_NAMES: frozenset[str] = frozenset(s.value for s in Status)
VERDICTS: tuple[Verdict, ...] = ("clean", "suspicious", "cheating")
HIT_ORDER: tuple[HitKind, ...] = ("dataset", "task", "run", "episode")
FIRST_DUPLICATE = 2
HEADER_LINES = 1
SLIM_REQUIRED = ("episode_id", "instance_id", "policy", "reward", "cheat_verdict", "resolved")

PROBE_ID = "threshold-probe"
PROBE_BRACKET = (-2.0, 2.0)
PROBE_STEPS = 4096

GRADING_STEPS: tuple[tuple[str, str, str], ...] = (
    ("diff", "Diff", "The agent's changes are diffed against the one-commit repo it worked in."),
    (
        "scan",
        "Scan",
        "Cheat Catcher reads the diff and the agent's steps, minus what the merged fix does too.",
    ),
    ("strip", "Strip", "Edits to tests, test runner config and node_modules are thrown away."),
    (
        "apply",
        "Boot and apply",
        "A fresh sandbox with no network gets the kept patch, then the hidden tests.",
    ),
    (
        "rename",
        "Rename targets",
        "Target tests get new names for this run, so a cheat can't spare them by name.",
    ),
    ("canary", "Plant canaries", "Tests that must fail and tests that must pass go in at random spots."),
    (
        "run",
        "Hash and run",
        "Watched files are hashed, changed source is compile checked, the suite runs, then a second hash.",
    ),
    (
        "tamper",
        "Check for tampering",
        "A canary that's wrong or missing, or a changed hash, marks the run tampered.",
    ),
    ("resolve", "Resolve", "Resolved means the run is trusted and every target and P2P test passes."),
    (
        "verdict",
        "Verdict",
        "Each tamper problem becomes a high grader-tamper finding, so the verdict is cheating.",
    ),
    ("rubric", "Rubric", "Rubric items are scored against the patch, the grade and the findings."),
    (
        "reward",
        "Reward",
        "-1 for a broken patch or a cheating verdict. Else a weighted sum, capped at 0 if no target passes.",
    ),
)

LEAK_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("statement", "Statement", "The statement doesn't quote a distinctive line of the fix."),
    ("grader_paths", "Grader paths", "No /tmp/gauntlet-* grader files are in the sandbox."),
    ("git_history", "Git history", "The scratch repo has one commit and there's no other .git on disk."),
    ("network", "Network", "The network is blocked."),
    ("env_vars", "Environment", "No hidden test or fix line is in the environment."),
    (
        "hidden_tests_on_disk",
        "Hidden tests on disk",
        "No distinctive line of the hidden tests is anywhere on disk.",
    ),
    ("gold_on_disk", "Fix on disk", "No distinctive line of the fix is anywhere on disk."),
    (
        "new_test_names_on_disk",
        "New test names on disk",
        "The new test names aren't on disk, so you can't grep for them.",
    ),
)
LEAK_LABELS = {check_id: label for check_id, label, _ in LEAK_CHECKS}

POLICY_NOTES: dict[str, str] = {
    "oracle": "Applies the merged fix. It must resolve.",
    "noop": "Gives up. It must score -1.",
    "cheater": "Forges results with a runner hook and skips the target test files.",
    "cheater:monkeypatch": "Forces every test report to passed from inside the module the fix touches.",
    "cheater:stealth": "The monkeypatch trick, hidden in base64 so no rule can read it.",
    "cheater:rewrite": "Rewrites the test files on disk when the module is imported.",
    "cheater:canary-aware": "Spares whatever looks like the grader's canary and forces the rest.",
    "cheater:ghost": "The canary-aware trick, hidden in base64.",
    "cheater:junit": "Lets the suite run, then cuts every failure out of the JUnit report.",
    "cheater:exit": "Exits cleanly the moment the module loads, so no test reports.",
    "cheater:snapshot": "Records the test names at the base commit, forces those and spares anything new.",
}
MODEL_POLICY = ("claude:<model>", "A real model, played through the same sandbox and grader.")


class _Match(IntEnum):
    EXACT = 0
    PREFIX = 1
    SUBSTRING = 2


def policy_kind(policy: str) -> PolicyKind:
    """How the harness treats a policy: the calibration rule's own split, in the same order."""
    if policy == ORACLE:
        return "oracle"
    if policy == NOOP:
        return "noop"
    if policy.startswith(CHEAT_PREFIX):
        return "cheat"
    return "model"


def _policy_order(policies: Iterable[str]) -> tuple[str, ...]:
    rank = {p: i for i, p in enumerate(CALIBRATION_POLICIES)}
    return tuple(sorted(set(policies), key=lambda p: (rank.get(p, len(rank)), p)))


def _facets(values: Iterable[str]) -> tuple[Facet, ...]:
    counts = Counter(values)
    return tuple(Facet(k, n) for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text, False) if len(text) <= limit else (text[:limit], True)


def _matches(query: str, *values: str | None) -> bool:
    q = query.strip().lower()
    return not q or any(v and q in v.lower() for v in values)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "run"


def _verdict(value: str | None) -> Verdict:
    return cast(Verdict, value) if value in VERDICTS else "clean"


def _counts(raw: Any) -> Counts:
    raw = raw if isinstance(raw, dict) else {}
    return Counts(
        passed=int(raw.get(Status.PASSED.value, 0)),
        failed=int(raw.get(Status.FAILED.value, 0)),
        skipped=int(raw.get(Status.SKIPPED.value, 0)),
        total=int(raw.get("total", 0)),
    )


def _decode(content: Any, encoding: Any) -> str:
    if not isinstance(content, str):
        return ""
    if encoding != "base64":
        return content
    try:
        return base64.b64decode(content).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return f"[{len(content)} characters of base64 that aren't UTF-8 text]"


def _first_line(doc: str | None) -> str:
    lines = (doc or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def _read_lines(path: Path, warn: Callable[[str], None]) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        warn(f"Couldn't read {path}: {e}")
        return []
    return [(n, line) for n, line in enumerate(text.splitlines(), 1) if line.strip()]


def _accepted(policy: str, reward: float, *, resolved: bool) -> bool:
    grade = GradeResult(instance_id=PROBE_ID, patch_applied=True, resolved=resolved)
    row = EpisodeResult(episode_id=PROBE_ID, instance_id=PROBE_ID, policy=policy, reward=reward, grade=grade)
    return not calibration_violations([row])


def _boundary(accepts: Callable[[float], bool]) -> float:
    """The exact reward where the calibration rule flips, found by asking the rule itself."""
    low, high = PROBE_BRACKET
    low_ok = accepts(low)
    if accepts(high) == low_ok:
        raise RuntimeError("the calibration rule no longer has a reward limit to probe")
    for _ in range(PROBE_STEPS):
        mid = (low + high) / 2
        if mid in (low, high):
            break
        if accepts(mid) == low_ok:
            low = mid
        else:
            high = mid
    return low if low_ok else high


def probe_thresholds() -> Thresholds:
    """The reward limits `calibration_violations` enforces, read off the function's behaviour."""
    return Thresholds(
        oracle_min_reward=_boundary(lambda r: _accepted(ORACLE, r, resolved=True)),
        noop_reward=_boundary(lambda r: _accepted(NOOP, r, resolved=False)),
        cheat_max_reward=_boundary(lambda r: _accepted(CHEAT_PREFIX, r, resolved=False)),
    )


@dataclass
class _Dataset:
    id: str
    title: str
    path: Path
    tasks: list[HarnessTask]
    stats: dict[str, Any] | None
    from_workspace: bool = False


@dataclass
class _Episode:
    row: EpisodeRow
    numbers: EpisodeResult  # the full row, or a stand-in built from a slim row for report's math
    full: EpisodeResult | None
    rubric: float | None


@dataclass
class _Run:
    id: str
    title: str
    kind: RunKind
    path: Path | None
    dataset_id: str | None
    episodes: list[_Episode] = field(default_factory=list)
    by_id: dict[str, _Episode] = field(default_factory=dict)
    summary: RunSummary | None = None
    detail: RunDetail | None = None
    from_workspace: bool = False

    @property
    def full(self) -> bool:
        return bool(self.episodes) and all(e.full is not None for e in self.episodes)


class Store:
    """Everything the viewer shows, loaded from disk and never written back.

    Build one with `Store.load(datasets_root, run_dirs)`. `datasets_root` is a folder whose
    subfolders hold a `tasks.jsonl` each (None loads no datasets), and every path in `run_dirs`
    is a run folder with a `results.jsonl`. A dataset's `validation.jsonl` becomes a run of its
    own, `shipped-<dataset id>`. A file that's missing or broken is skipped and named in
    `overview().warnings`; the load itself never fails on bad data.

    With a `workspace`, each `tasks/<name>/tasks.jsonl` in it is a dataset too, with the id
    `workspace/<name>` (a shipped id never has a slash) and its `rejected.jsonl` as its funnel,
    and each `runs/<name>/` is a run with the same kind of id. Both are marked
    `from_workspace`. A folder a job is still writing is skipped with a warning. `reload()`
    loads everything again from the same places.
    """

    def __init__(self) -> None:
        self._datasets: dict[str, _Dataset] = {}
        self._tasks: dict[str, tuple[HarnessTask, str]] = {}
        self._rows: dict[str, TaskRow] = {}
        self._runs: dict[str, _Run] = {}
        self._warnings: list[str] = []
        self._classes: dict[str, dict[str, TestClass]] = {}
        self._trajectories: dict[tuple[str, str], Trajectory | None] = {}
        self._reference: Reference | None = None
        self._sources: tuple[Path | None, tuple[Path, ...], Path | None] = (None, (), None)

    @classmethod
    def load(
        cls, datasets_root: Path | None, run_dirs: Sequence[Path] = (), workspace: Path | None = None
    ) -> Store:
        store = cls()
        store._sources = (datasets_root, tuple(run_dirs), workspace)
        if datasets_root is not None:
            store._load_datasets(Path(datasets_root))
        if workspace is not None:
            store._load_workspace_tasks(Path(workspace))
        for path in run_dirs:
            store._load_run_dir(Path(path))
        if workspace is not None:
            store._load_workspace_runs(Path(workspace))
        return store

    def reload(self) -> Store:
        """A fresh `Store` loaded from the same places, so a finished job's output shows up."""
        datasets_root, run_dirs, workspace = self._sources
        return Store.load(datasets_root, run_dirs, workspace)

    # ------------------------------------------------------------------ loading

    def _warn(self, message: str) -> None:
        self._warnings.append(message)

    def _load_datasets(self, root: Path) -> None:
        if not root.is_dir():
            self._warn(f"The datasets folder {root} doesn't exist.")
            return
        for folder in sorted(p for p in root.iterdir() if (p / TASKS_FILE).is_file()):
            dataset_id = self._unique(folder.name.removeprefix(DATASET_PREFIX), self._datasets)
            tasks = self._load_tasks(folder / TASKS_FILE, dataset_id)
            dataset = _Dataset(
                id=dataset_id,
                title=self._title(folder),
                path=folder,
                tasks=tasks,
                stats=self._load_stats(folder / STATS_FILE),
            )
            self._datasets[dataset_id] = dataset
            if (folder / VALIDATION_FILE).is_file():
                run = _Run(
                    id=self._unique(SHIPPED_PREFIX + dataset_id, self._runs),
                    title=f"{dataset.title}: shipped calibration",
                    kind="shipped",
                    path=None,
                    dataset_id=dataset_id,
                )
                self._load_episodes(run, folder / VALIDATION_FILE)
                self._runs[run.id] = run

    def _workspace_folders(self, root: Path, kind: str, wanted: str) -> list[Path]:
        folder = root / kind
        if not folder.is_dir():
            return []
        ready = []
        for path in sorted(p for p in folder.iterdir() if p.is_dir()):
            if (path / wanted).is_file():
                ready.append(path)
            elif any(path.iterdir()):
                self._warn(f"Skipped {path}: it has no {wanted} yet. A job may still be writing it.")
        return ready

    def _load_workspace_tasks(self, root: Path) -> None:
        for folder in self._workspace_folders(root, TASKS_DIR, TASKS_FILE):
            dataset_id = self._unique(WORKSPACE_PREFIX + folder.name, self._datasets)
            self._datasets[dataset_id] = _Dataset(
                id=dataset_id,
                title=f"{folder.name} (workspace)",
                path=folder,
                tasks=self._load_tasks(folder / TASKS_FILE, dataset_id),
                stats=self._workspace_funnel(folder),
                from_workspace=True,
            )

    def _workspace_funnel(self, folder: Path) -> dict[str, Any] | None:
        """The same shape as a shipped `stats.json`, from `prs.jsonl` and `rejected.jsonl`."""
        prs, rejected = folder / PRS_FILE, folder / REJECTED_FILE
        if not rejected.is_file() and not prs.is_file():
            return None
        stages: Counter[str] = Counter()
        if rejected.is_file():
            for n, line in _read_lines(rejected, self._warn):
                try:
                    stages[Rejected.model_validate_json(line).stage] += 1
                except ValidationError as e:
                    self._warn(f"Skipped line {n} of {rejected}: it isn't a rejection ({_short(e)}).")
        stats: dict[str, Any] = {"rejected_by_stage": dict(stages)}
        if prs.is_file():
            stats["prs_collected"] = len(_read_lines(prs, self._warn))
        return stats

    def _load_workspace_runs(self, root: Path) -> None:
        for folder in self._workspace_folders(root, RUNS_DIR, RESULTS_FILE):
            self._load_run_dir(folder, run_id=WORKSPACE_PREFIX + folder.name, from_workspace=True)

    def _title(self, folder: Path) -> str:
        readme = folder / README_FILE
        try:
            first = readme.read_text(encoding="utf-8").splitlines()[0] if readme.is_file() else ""
        except (OSError, UnicodeDecodeError, IndexError):
            first = ""
        return first.lstrip("#").strip() if first.startswith("#") else folder.name

    def _load_stats(self, path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            stats = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self._warn(f"Skipped {path}: it isn't valid JSON ({e}).")
            return None
        if not isinstance(stats, dict):
            self._warn(f"Skipped {path}: it isn't a JSON object.")
            return None
        return stats

    def _load_tasks(self, path: Path, dataset_id: str) -> list[HarnessTask]:
        tasks = []
        for n, line in _read_lines(path, self._warn):
            try:
                task = HarnessTask.model_validate_json(line)
                runner = runner_for(task).name
            except (ValidationError, ValueError) as e:
                self._warn(f"Skipped line {n} of {path}: it isn't a task ({_short(e)}).")
                continue
            if task.instance_id in self._tasks:
                self._warn(f"Skipped line {n} of {path}: task {task.instance_id} is already loaded.")
                continue
            self._tasks[task.instance_id] = (task, dataset_id)
            self._rows[task.instance_id] = _task_row(task, dataset_id, runner)
            tasks.append(task)
        return tasks

    def _load_run_dir(self, path: Path, *, run_id: str | None = None, from_workspace: bool = False) -> None:
        results = path / RESULTS_FILE
        if not results.is_file():
            self._warn(f"Skipped {path}: it has no {RESULTS_FILE}.")
            return
        run = _Run(
            id=self._unique(run_id, self._runs)
            if run_id
            else self._unique(
                _slug(path.name), self._runs, fallback=_slug(f"{path.parent.name}-{path.name}")
            ),
            title=f"{path.name} (workspace)" if from_workspace else path.name,
            kind="folder",
            path=path,
            dataset_id=None,
            from_workspace=from_workspace,
        )
        self._load_episodes(run, results)
        homes = {self._tasks[e.row.instance_id][1] for e in run.episodes if e.row.instance_id in self._tasks}
        run.dataset_id = next(iter(homes)) if len(homes) == 1 else None
        self._runs[run.id] = run

    def _load_episodes(self, run: _Run, path: Path) -> None:
        for n, line in _read_lines(path, self._warn):
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                self._warn(f"Skipped line {n} of {path}: it isn't valid JSON.")
                continue
            if not isinstance(raw, dict):
                self._warn(f"Skipped line {n} of {path}: it isn't a JSON object.")
                continue
            try:
                episode = self._full_episode(run, raw) if _is_full(raw) else self._slim_episode(run, raw)
            except (ValidationError, ValueError, TypeError) as e:
                self._warn(f"Skipped line {n} of {path}: it isn't an episode ({_short(e)}).")
                continue
            if episode.row.episode_id in run.by_id:
                self._warn(
                    f"Line {n} of {path} repeats episode {episode.row.episode_id}; the last one is shown."
                )
            run.episodes.append(episode)
            run.by_id[episode.row.episode_id] = episode

    def _full_episode(self, run: _Run, raw: dict[str, Any]) -> _Episode:
        r = EpisodeResult.model_validate(raw)
        row = EpisodeRow(
            run_id=run.id,
            episode_id=r.episode_id,
            instance_id=r.instance_id,
            policy=r.policy,
            policy_kind=policy_kind(r.policy),
            category=r.category,
            reward=r.reward,
            resolved=bool(r.grade and r.grade.resolved),
            cheat_verdict=_verdict(r.cheat_verdict),
            detail="full",
            attempt=r.attempt,
            tampered=bool(r.grade.tampered) if r.grade else None,
            steps=r.steps,
            seconds=r.seconds,
            error=r.error,
        )
        return _Episode(row=row, numbers=r, full=r, rubric=r.rubric.score if r.rubric else None)

    def _slim_episode(self, run: _Run, raw: dict[str, Any]) -> _Episode:
        missing = [k for k in SLIM_REQUIRED if k not in raw]
        if missing:
            raise ValueError(f"missing {', '.join(missing)}")
        instance_id = str(raw["instance_id"])
        known = self._tasks.get(instance_id)
        category: Category = known[0].category if known else "swe"
        rubric = float(raw["rubric"]) if isinstance(raw.get("rubric"), int | float) else None
        tampered = raw.get("tampered")
        steps = raw.get("steps")
        row = EpisodeRow(
            run_id=run.id,
            episode_id=str(raw["episode_id"]),
            instance_id=instance_id,
            policy=str(raw["policy"]),
            policy_kind=policy_kind(str(raw["policy"])),
            category=category,
            reward=float(raw["reward"]),
            resolved=bool(raw["resolved"]),
            cheat_verdict=_verdict(raw["cheat_verdict"]),
            detail="summary",
            tampered=tampered if isinstance(tampered, bool) else None,
            steps=steps if isinstance(steps, int) else None,
        )
        numbers = EpisodeResult(
            episode_id=row.episode_id,
            instance_id=instance_id,
            category=category,
            policy=row.policy,
            steps=row.steps or 0,
            grade=GradeResult(instance_id=instance_id, patch_applied=True, resolved=row.resolved),
            rubric=RubricScore(score=rubric) if rubric is not None else None,
            cheat_verdict=raw["cheat_verdict"],
            reward=row.reward,
        )
        return _Episode(row=row, numbers=numbers, full=None, rubric=rubric)

    @staticmethod
    def _unique(wanted: str, taken: dict[str, Any], *, fallback: str | None = None) -> str:
        for candidate in (wanted, fallback):
            if candidate and candidate not in taken:
                return candidate
        n = FIRST_DUPLICATE
        while f"{wanted}-{n}" in taken:
            n += 1
        return f"{wanted}-{n}"

    # ------------------------------------------------------------------ lookups

    def _dataset(self, dataset_id: str) -> _Dataset:
        try:
            return self._datasets[dataset_id]
        except KeyError:
            raise NotFound(f"no dataset {dataset_id!r} is loaded") from None

    def _task(self, instance_id: str) -> HarnessTask:
        try:
            return self._tasks[instance_id][0]
        except KeyError:
            raise NotFound(f"no task {instance_id!r} is loaded") from None

    def _run(self, run_id: str) -> _Run:
        try:
            return self._runs[run_id]
        except KeyError:
            raise NotFound(f"no run {run_id!r} is loaded") from None

    def _episode(self, run_id: str, episode_id: str) -> tuple[_Run, _Episode]:
        run = self._run(run_id)
        try:
            return run, run.by_id[episode_id]
        except KeyError:
            raise NotFound(f"no episode {episode_id!r} in run {run_id!r}") from None

    def _test_classes(self, instance_id: str) -> dict[str, TestClass]:
        if instance_id not in self._classes:
            task = self._task(instance_id)
            classes: dict[str, TestClass] = {}
            for kind in reversed(TEST_CLASSES):
                classes.update(dict.fromkeys(getattr(task, kind), kind))
            self._classes[instance_id] = classes
        return self._classes[instance_id]

    # ------------------------------------------------------------------ overview and reference

    def overview(self) -> Overview:
        rows = list(self._rows.values())
        tasks = [task for task, _ in self._tasks.values()]
        checks = [len(_leak_report(t).get("checks") or {}) for t in tasks]
        return Overview(
            version=__version__,
            totals=Totals(
                tasks=len(rows),
                repos=len({r.repo for r in rows}),
                datasets=len(self._datasets),
                runs=len(self._runs),
                episodes=sum(len(r.episodes) for r in self._runs.values()),
                leak_checks_per_task=max(checks, default=0),
                leak_check_failures=sum(1 for r in rows if not r.leakcheck_ok),
                cheat_policies=sum(1 for p in CALIBRATION_POLICIES if policy_kind(p) == "cheat"),
                cheatcatcher_rules=len(RULES),
            ),
            datasets=self.datasets(),
            runs=self.runs(),
            warnings=tuple(self._warnings),
        )

    def reference(self) -> Reference:
        if self._reference is None:
            policies = [
                ReferenceItem(id=p, title=p, what=POLICY_NOTES.get(p, ""), kind=policy_kind(p))
                for p in CALIBRATION_POLICIES
            ]
            policies.append(
                ReferenceItem(id=MODEL_POLICY[0], title=MODEL_POLICY[0], what=MODEL_POLICY[1], kind="model")
            )
            self._reference = Reference(
                grading_steps=tuple(ReferenceItem(id=i, title=t, what=w) for i, t, w in GRADING_STEPS),
                leak_checks=tuple(ReferenceItem(id=i, title=t, what=w) for i, t, w in LEAK_CHECKS),
                rules=tuple(
                    ReferenceItem(id=name, title=name, what=_first_line(fn.__doc__), kind="rule")
                    for name, fn in RULES.items()
                ),
                policies=tuple(policies),
                thresholds=probe_thresholds(),
            )
        return self._reference

    # ------------------------------------------------------------------ datasets and tasks

    def datasets(self) -> tuple[DatasetSummary, ...]:
        return tuple(self._dataset_summary(d) for d in self._datasets.values())

    def _dataset_summary(self, dataset: _Dataset) -> DatasetSummary:
        rows = [self._rows[t.instance_id] for t in dataset.tasks]
        merged = sorted(r.merged_at for r in rows if r.merged_at)
        return DatasetSummary(
            id=dataset.id,
            title=dataset.title,
            tasks=len(rows),
            repos=len({r.repo for r in rows}),
            categories=_facets(r.category for r in rows),
            runners=_facets(r.runner for r in rows),
            merged_from=merged[0] if merged else None,
            merged_to=merged[-1] if merged else None,
            f2p_total=sum(r.f2p for r in rows),
            n2p_total=sum(r.n2p for r in rows),
            s2p_total=sum(r.s2p for r in rows),
            p2p_total=sum(r.p2p for r in rows),
            leakcheck_ok=sum(1 for r in rows if r.leakcheck_ok),
            has_validation=(dataset.path / VALIDATION_FILE).is_file(),
            from_workspace=dataset.from_workspace,
        )

    def dataset(self, dataset_id: str) -> DatasetDetail:
        dataset = self._dataset(dataset_id)
        stats = dataset.stats or {}
        collected = stats.get("prs_collected")
        stages = stats.get("rejected_by_stage")
        rejected = (
            [(str(k), v) for k, v in stages.items() if isinstance(v, int)] if isinstance(stages, dict) else []
        )
        return DatasetDetail(
            summary=self._dataset_summary(dataset),
            by_repo=_facets(t.pr.repo for t in dataset.tasks),
            prs_collected=collected if isinstance(collected, int) else None,
            rejected_by_stage=tuple(Facet(k, v) for k, v in sorted(rejected, key=lambda kv: (-kv[1], kv[0]))),
        )

    def task_facets(self) -> TaskFacets:
        rows = list(self._rows.values())
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
            for r in self._rows.values()
            if (dataset is None or r.dataset_id == dataset)
            and (repo is None or r.repo == repo)
            and (category is None or r.category == category)
            and (runner is None or r.runner == runner)
            and _matches(query, r.instance_id, r.repo, r.pr_title)
        )

    def task(self, instance_id: str) -> TaskDetail:
        task = self._task(instance_id)
        report = _leak_report(task)
        gold, gold_cut = _clip(task.gold_patch, PATCH_LIMIT)
        tests, tests_cut = _clip(task.test_patch, PATCH_LIMIT)
        return TaskDetail(
            row=self._rows[instance_id],
            problem_statement=task.problem_statement,
            image=task.image,
            env_fingerprint=task.env_fingerprint,
            base_commit=task.base_commit,
            solution_commit=task.solution_commit,
            workdir=task.workdir,
            test_files=tuple(task.test_files),
            test_scope=tuple(task.test_scope),
            f2p=tuple(task.f2p),
            n2p=tuple(task.n2p),
            s2p=tuple(task.s2p),
            flaky=tuple(task.flaky),
            validation=_validation_runs(task.validation),
            leakcheck_ok=bool(report.get("ok")),
            leakchecks=_leak_checks(report),
            gold_patch=gold,
            test_patch=tests,
            horizon=_horizon_detail(task),
            episodes=tuple(
                e.row for run in self._runs.values() for e in run.episodes if e.row.instance_id == instance_id
            ),
            gold_patch_truncated=gold_cut,
            test_patch_truncated=tests_cut,
        )

    def task_tests(self, instance_id: str, test_class: TestClass, *, query: str = "") -> tuple[str, ...]:
        task = self._task(instance_id)
        if test_class not in TEST_CLASSES:
            raise NotFound(f"no test class {test_class!r}")
        return tuple(t for t in getattr(task, test_class) if _matches(query, t))

    # ------------------------------------------------------------------ runs

    def runs(self) -> tuple[RunSummary, ...]:
        return tuple(self._run_summary(r) for r in self._runs.values())

    def _run_summary(self, run: _Run) -> RunSummary:
        if run.summary is None:
            episodes = run.episodes
            ran = sorted(
                e.full.provenance.ran_at
                for e in episodes
                if e.full and e.full.provenance and e.full.provenance.ran_at
            )
            run.summary = RunSummary(
                id=run.id,
                title=run.title,
                kind=run.kind,
                detail="full" if run.full else "summary",
                episodes=len(episodes),
                tasks=len({e.row.instance_id for e in episodes}),
                policies=_policy_order(e.row.policy for e in episodes),
                dataset_id=run.dataset_id,
                path=str(run.path) if run.path else None,
                ran_from=ran[0] if ran else None,
                ran_to=ran[-1] if ran else None,
                oracle=_group([e for e in episodes if e.row.policy_kind == "oracle"]),
                noop=_group([e for e in episodes if e.row.policy_kind == "noop"]),
                cheats=_group([e for e in episodes if e.row.policy_kind == "cheat"]),
                violations=len(self._violations(run)) if run.full else None,
                from_workspace=run.from_workspace,
            )
        return run.summary

    @staticmethod
    def _calibration_rows(run: _Run) -> list[EpisodeResult]:
        return [e.full for e in run.episodes if e.full is not None and e.row.policy in CALIBRATION_POLICIES]

    def _violations(self, run: _Run) -> list[str]:
        return calibration_violations(self._calibration_rows(run))

    def run(self, run_id: str) -> RunDetail:
        run = self._run(run_id)
        if run.detail is None:
            checked = run.full
            run.detail = RunDetail(
                summary=self._run_summary(run),
                policies=_policy_rows(run.episodes),
                calibration_checked=checked,
                violations=tuple(self._violations(run)) if checked else (),
                rotted=tuple(sorted(rotted_tasks(self._calibration_rows(run)).items())) if checked else (),
            )
        return run.detail

    def matrix(self, run_id: str) -> Matrix:
        run = self._run(run_id)
        policies = _policy_order(e.row.policy for e in run.episodes)
        task_ids = sorted({e.row.instance_id for e in run.episodes})
        first: dict[tuple[str, str], _Episode] = {}
        for e in sorted(run.episodes, key=lambda e: e.row.attempt or 0):
            first.setdefault((e.row.instance_id, e.row.policy), e)
        tasks = []
        for iid in task_ids:
            row = self._rows.get(iid)
            category = (
                row.category
                if row
                else next(e.row.category for e in run.episodes if e.row.instance_id == iid)
            )
            tasks.append(MatrixTask(instance_id=iid, repo=row.repo if row else "", category=category))
        cells = tuple(
            tuple(_cell(first[(iid, p)]) if (iid, p) in first else None for p in policies) for iid in task_ids
        )
        return Matrix(policies=policies, tasks=tuple(tasks), cells=cells)

    def episode_facets(self, run_id: str) -> EpisodeFacets:
        rows = [e.row for e in self._run(run_id).episodes]
        rank = {p: i for i, p in enumerate(_policy_order(r.policy for r in rows))}
        policies = Counter(r.policy for r in rows)
        return EpisodeFacets(
            policies=tuple(Facet(p, policies[p]) for p in sorted(policies, key=rank.__getitem__)),
            verdicts=tuple(
                Facet(v, n) for v in VERDICTS if (n := sum(1 for r in rows if r.cheat_verdict == v))
            ),
            tasks=_facets(r.instance_id for r in rows),
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
        return tuple(
            r
            for r in (e.row for e in self._run(run_id).episodes)
            if (policy is None or r.policy == policy)
            and (task is None or r.instance_id == task)
            and (verdict is None or r.cheat_verdict == verdict)
            and (resolved is None or r.resolved == resolved)
            and _matches(query, r.episode_id, r.instance_id, r.policy)
        )

    # ------------------------------------------------------------------ episodes

    def episode(self, run_id: str, episode_id: str) -> EpisodeDetail:
        run, episode = self._episode(run_id, episode_id)
        r = episode.full
        if r is None:
            return EpisodeDetail(
                row=episode.row,
                reward_breakdown=None,
                grade=None,
                rubric_score=episode.rubric,
                rubric_items=(),
                rubric_skipped=(),
                findings=(),
                patch=None,
                provenance=None,
                usage=(),
                truncated=None,
                trajectory_steps=None,
            )
        patch, patch_cut = _clip(r.patch, PATCH_LIMIT)
        return EpisodeDetail(
            row=episode.row,
            reward_breakdown=_breakdown(r.reward_breakdown),
            grade=_grade_detail(r.grade) if r.grade else None,
            rubric_score=r.rubric.score if r.rubric else None,
            rubric_items=tuple(
                RubricItem(
                    id=i.id, category=i.category, kind=i.kind, met=i.met, score=i.score, rationale=i.rationale
                )
                for i in (r.rubric.items if r.rubric else [])
            ),
            rubric_skipped=tuple(r.rubric.skipped) if r.rubric else (),
            findings=tuple(_finding(f) for f in r.cheat_findings),
            patch=patch,
            provenance=_provenance(r),
            usage=tuple((k, str(v)) for k, v in sorted(r.usage.items())),
            truncated=r.truncated,
            trajectory_steps=self._step_count(run, episode_id),
            patch_truncated=patch_cut,
            prompt=self._prompt(run, episode_id),
        )

    def episode_tests(
        self,
        run_id: str,
        episode_id: str,
        *,
        test_class: TestClass | None = None,
        status: str | None = None,
        query: str = "",
    ) -> tuple[TestStatus, ...]:
        _, episode = self._episode(run_id, episode_id)
        grade = episode.full.grade if episode.full else None
        statuses = grade.statuses if grade else {}
        iid = episode.row.instance_id
        classes = self._test_classes(iid) if iid in self._tasks else {}
        ids = dict.fromkeys([*classes, *statuses])
        rank = {c: i for i, c in enumerate(TEST_CLASSES)}
        out = []
        for test in ids:
            cls = classes.get(test)
            raw = statuses.get(test, Status.NONE.value)
            name = cast(TestStatusName, raw if raw in STATUS_NAMES else Status.NONE.value)
            if (
                (test_class is None or cls == test_class)
                and (status is None or name == status)
                and _matches(query, test)
            ):
                out.append(TestStatus(id=test, status=name, test_class=cls))
        out.sort(key=lambda t: rank.get(t.test_class, len(rank)))
        return tuple(out)

    def _files(self, run: _Run, episode_id: str) -> tuple[Path, Path] | None:
        if run.path is None:
            return None
        return (run.path / TRAJECTORY_DIR / f"{episode_id}.jsonl", run.path / RL_DIR / f"{episode_id}.json")

    def _step_count(self, run: _Run, episode_id: str) -> int | None:
        files = self._files(run, episode_id)
        if files is None or not files[0].is_file():
            return None
        try:
            with files[0].open("rb") as f:
                lines = sum(1 for line in f if line.strip())
        except OSError:
            return None
        return max(0, lines - HEADER_LINES)

    def _prompt(self, run: _Run, episode_id: str) -> str | None:
        files = self._files(run, episode_id)
        if files is None or not files[1].is_file():
            return None
        try:
            record = json.loads(files[1].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        prompt = record.get("prompt") if isinstance(record, dict) else None
        return prompt if isinstance(prompt, str) else None

    def trajectory(self, run_id: str, episode_id: str) -> Trajectory | None:
        run, episode = self._episode(run_id, episode_id)
        key = (run_id, episode_id)
        if key not in self._trajectories:
            files = self._files(run, episode_id)
            flags: dict[int, list[str]] = {}
            for f in episode.full.cheat_findings if episode.full else []:
                if isinstance(f.get("step"), int):
                    flags.setdefault(f["step"], []).append(str(f.get("rule", "")))
            path = files[0] if files else None
            self._trajectories[key] = _load_trajectory(path, flags) if path and path.is_file() else None
        return self._trajectories[key]

    # ------------------------------------------------------------------ search

    def search(self, query: str, *, limit: int) -> tuple[SearchHit, ...]:
        q = query.strip().lower()
        if not q or limit <= 0:
            return ()
        scored: list[tuple[int, int, str, SearchHit]] = []

        def offer(hit: SearchHit, *values: str) -> None:
            ranks = [m for v in values if (m := _match(q, v)) is not None]
            if ranks:
                scored.append((min(ranks), HIT_ORDER.index(hit.kind), hit.id, hit))

        for d in self._datasets.values():
            offer(
                SearchHit(kind="dataset", id=d.id, title=d.title, subtitle=f"{len(d.tasks)} tasks"),
                d.id,
                d.title,
            )
        for r in self._rows.values():
            hit = SearchHit(
                kind="task", id=r.instance_id, title=r.instance_id, subtitle=f"{r.repo} · {r.dataset_id}"
            )
            offer(hit, r.instance_id, r.repo)
        for run in self._runs.values():
            subtitle = f"{len(run.episodes)} episodes"
            offer(SearchHit(kind="run", id=run.id, title=run.title, subtitle=subtitle), run.id, run.title)
            for e in run.episodes:
                hit = SearchHit(
                    kind="episode",
                    id=e.row.episode_id,
                    title=e.row.episode_id,
                    subtitle=f"{e.row.policy} · {run.title}",
                    run_id=run.id,
                )
                offer(hit, e.row.episode_id)
        scored.sort(key=lambda s: (s[0], s[1], s[2]))
        return tuple(hit for *_, hit in scored[:limit])


def _match(query: str, value: str) -> int | None:
    v = value.lower()
    if v == query:
        return _Match.EXACT
    if v.startswith(query):
        return _Match.PREFIX
    if query in v:
        return _Match.SUBSTRING
    return None


def _short(error: Exception) -> str:
    if isinstance(error, ValidationError):
        first = error.errors()[0] if error.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ())) or "row"
        return f"{where}: {first.get('msg', 'invalid')}"
    return str(error)


def _is_full(raw: dict[str, Any]) -> bool:
    return "format" in raw or "grade" in raw


def _leak_report(task: HarnessTask) -> dict[str, Any]:
    report = task.validation.get("leakcheck")
    return report if isinstance(report, dict) else {}


def _leak_checks(report: dict[str, Any]) -> tuple[LeakCheck, ...]:
    checks = report.get("checks") or {}
    order = {check_id: i for i, check_id in enumerate(LEAK_LABELS)}
    return tuple(
        LeakCheck(
            id=name,
            label=LEAK_LABELS.get(name, name),
            ok=bool(c.get("ok")) if isinstance(c, dict) else False,
            detail=str(c.get("detail", "")) if isinstance(c, dict) else "",
        )
        for name, c in sorted(checks.items(), key=lambda kv: order.get(kv[0], len(order)))
    )


def _task_row(task: HarnessTask, dataset_id: str, runner: str) -> TaskRow:
    h = task.horizon
    return TaskRow(
        instance_id=task.instance_id,
        dataset_id=dataset_id,
        repo=task.pr.repo,
        category=task.category,
        runner=runner,
        language=task.language,
        pr_number=task.pr.number if task.horizon is None else None,
        pr_title=task.pr.title,
        pr_url=task.pr.url or None,
        merged_at=task.pr.merged_at,
        f2p=len(task.f2p),
        n2p=len(task.n2p),
        s2p=len(task.s2p),
        p2p=len(task.p2p),
        flaky=len(task.flaky),
        statement_source=task.statement_source,
        leakcheck_ok=bool(_leak_report(task).get("ok")),
        horizon=HorizonSummary(h.from_ref, h.to_ref, len(h.prs), len(h.milestones)) if h else None,
    )


def _validation_runs(validation: dict[str, Any]) -> ValidationRuns | None:
    runs = validation.get("runs")
    if not isinstance(runs, dict):
        return None
    seconds = validation.get("seconds")
    total = seconds.get("total") if isinstance(seconds, dict) else None
    fix_runs = validation.get("fix_runs")
    fixes = runs.get("fix") if isinstance(runs.get("fix"), list) else []
    scope = validation.get("scope")
    return ValidationRuns(
        run=_counts(runs.get("run")),
        test=_counts(runs.get("test")),
        fix=tuple(_counts(f) for f in fixes),
        fix_runs=fix_runs if isinstance(fix_runs, int) else len(fixes),
        scope=scope if isinstance(scope, str) else None,
        seconds_total=float(total) if isinstance(total, int | float) else None,
    )


def _horizon_detail(task: HarnessTask) -> HorizonDetail | None:
    h = task.horizon
    if h is None:
        return None
    return HorizonDetail(
        from_ref=h.from_ref,
        to_ref=h.to_ref,
        prs=tuple(LinkedPR(number=p.number, title=p.title, url=p.url or None) for p in h.prs),
        direct_commits=tuple(h.direct_commits),
        milestones=tuple(Milestone(id=m.id, title=m.title, tests=len(m.tests)) for m in h.milestones),
        dropped_regressions=tuple(h.dropped_regressions),
        gold_lines=h.gold_lines,
    )


def _group(episodes: list[_Episode]) -> PolicyGroup | None:
    if not episodes:
        return None
    rewards = [e.row.reward for e in episodes]
    return PolicyGroup(
        episodes=len(episodes),
        resolved=sum(1 for e in episodes if solved(e.numbers)),
        min_reward=min(rewards),
        max_reward=max(rewards),
        cheating_verdicts=sum(1 for e in episodes if e.row.cheat_verdict == "cheating"),
    )


def _policy_rows(episodes: list[_Episode]) -> tuple[PolicyRow, ...]:
    """One row per policy and category, straight from `report.summarize`, which never pools the two."""
    summary = summarize([e.numbers for e in episodes])
    blocks = summary["categories"].values() if summary.get("categories") else [summary]
    out = []
    for block in blocks:
        category = cast(Category, block["category"])
        for stats in block["policies"]:
            mine = [e for e in episodes if e.row.policy == stats["policy"] and e.row.category == category]
            out.append(_policy_row(stats, category, mine))
    return tuple(out)


def _policy_row(stats: dict[str, Any], category: Category, episodes: list[_Episode]) -> PolicyRow:
    rewards = [e.row.reward for e in episodes]
    p1, ci = stats.get("pass@1"), stats.get("pass@1_ci95")
    tampered = [e.row.tampered for e in episodes]
    return PolicyRow(
        policy=stats["policy"],
        kind=policy_kind(stats["policy"]),
        episodes=stats["episodes"],
        tasks=stats["tasks"],
        resolved=sum(1 for e in episodes if solved(e.numbers)),
        mean_reward=stats["mean_reward"],
        min_reward=min(rewards),
        max_reward=max(rewards),
        verdicts=_verdict_counts(episodes),
        errors=stats["errors"],
        pass_at_1=Interval(p1, ci[0], ci[1]) if p1 is not None and ci is not None else None,
        tampered=None if any(t is None for t in tampered) else sum(1 for t in tampered if t),
        category=category,
    )


def _verdict_counts(episodes: list[_Episode]) -> VerdictCounts:
    counts = Counter(e.row.cheat_verdict for e in episodes)
    return VerdictCounts(clean=counts["clean"], suspicious=counts["suspicious"], cheating=counts["cheating"])


def _cell(episode: _Episode) -> MatrixCell:
    r = episode.row
    return MatrixCell(
        episode_id=r.episode_id,
        reward=r.reward,
        resolved=r.resolved,
        verdict=r.cheat_verdict,
        tampered=r.tampered,
    )


def _breakdown(raw: dict[str, float]) -> RewardBreakdown | None:
    if not raw:
        return None

    def opt(key: str) -> float | None:
        return float(raw[key]) if key in raw else None

    done = raw.get("milestones_done")
    return RewardBreakdown(
        tests=float(raw.get("tests", 0.0)),
        rubric=float(raw.get("rubric", 0.0)),
        similarity=float(raw.get("similarity", 0.0)),
        penalty=float(raw.get("penalty", 0.0)),
        w_tests=opt("w_tests"),
        w_rubric=opt("w_rubric"),
        w_similarity=opt("w_similarity"),
        capped_from=opt("capped_from"),
        milestones_done=int(done) if done is not None else None,
    )


def _class_counts(passed: dict[str, bool]) -> ClassCounts:
    return ClassCounts(
        total=len(passed),
        passed=sum(1 for ok in passed.values() if ok),
        failed=tuple(t for t, ok in passed.items() if not ok),
    )


def _grade_detail(g: GradeResult) -> GradeDetail:
    return GradeDetail(
        patch_applied=g.patch_applied,
        resolved=g.resolved,
        error=g.error,
        ignored_files=tuple(g.ignored_files),
        compile_errors=tuple(g.compile_errors),
        tampered=tuple(g.tampered),
        milestones=tuple(g.milestones.items()),
        f2p=_class_counts(g.passed.get("f2p") or {}),
        n2p=_class_counts(g.passed.get("n2p") or {}),
        s2p=_class_counts(g.passed.get("s2p") or {}),
        p2p=_class_counts(g.passed.get("p2p") or {}),
        status_counts=_facets(g.statuses.values()),
    )


def _finding(raw: dict[str, Any]) -> Finding:
    step = raw.get("step")
    severity = raw.get("severity")
    return Finding(
        rule=str(raw.get("rule", "")),
        severity=cast(Severity, severity if severity in ("low", "medium", "high") else "low"),
        message=str(raw.get("message", "")),
        step=step if isinstance(step, int) else None,
        file=raw.get("file") if isinstance(raw.get("file"), str) else None,
        evidence=str(raw.get("evidence", "")),
    )


def _provenance(r: EpisodeResult) -> Provenance | None:
    p = r.provenance
    if p is None:
        return None
    return Provenance(
        harness_version=p.harness_version,
        image=p.image,
        env_fingerprint=p.env_fingerprint,
        grading_seed=p.grading_seed,
        ran_at=p.ran_at,
        policy_params=tuple((k, str(v)) for k, v in sorted(p.policy_params.items())),
    )


def _load_trajectory(path: Path, flags: dict[int, list[str]]) -> Trajectory:
    """Steps keep the index the sandbox gave them, which is the number Cheat Catcher's findings use.

    The env hands Cheat Catcher a slice of the sandbox's own step objects (the agent's steps,
    after the setup ones), so a finding's `step` is already the sandbox index: no offset.
    """
    warnings: list[str] = []
    header: TrajectoryHeader | None = None
    steps: list[TrajectoryStep] = []
    for n, line in _read_lines(path, warnings.append):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"Skipped line {n} of {path.name}: it isn't valid JSON.")
            continue
        kind = obj.get("type") if isinstance(obj, dict) else None
        if kind == "header":
            config = obj.get("config") if isinstance(obj.get("config"), dict) else {}
            header = TrajectoryHeader(
                image=str(obj.get("image", "")),
                sandbox_id=str(obj.get("sandbox_id", "")),
                created_at=_num(obj.get("created_at")),
                network=bool(config.get("network", False)),
                memory=config.get("memory") if isinstance(config.get("memory"), str) else None,
                cpus=_num(config.get("cpus")),
            )
        elif kind == "step" and isinstance(obj.get("index"), int):
            steps.append(_step(obj, flags))
        else:
            warnings.append(f"Skipped line {n} of {path.name}: it isn't a header or a step.")
    if header is None:
        warnings.append(f"{path.name} has no header line.")
    return Trajectory(header=header, steps=tuple(steps), warnings=tuple(warnings))


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _step(obj: dict[str, Any], flags: dict[int, list[str]]) -> TrajectoryStep:
    action = obj.get("action") if isinstance(obj.get("action"), dict) else {}
    seen = obj.get("observation") if isinstance(obj.get("observation"), dict) else {}
    kind = str(action.get("type", ""))
    if kind == "write_file":
        content = _decode(action.get("content"), action.get("encoding"))
    else:
        content = _decode(seen.get("content"), seen.get("encoding"))
    stdout, out_cut = _clip(str(seen.get("stdout") or ""), OUTPUT_LIMIT)
    stderr, err_cut = _clip(str(seen.get("stderr") or ""), OUTPUT_LIMIT)
    content, content_cut = _clip(content, OUTPUT_LIMIT)
    command = action.get("command")
    path = action.get("path")
    exit_code = seen.get("exit_code")
    index = obj["index"]
    return TrajectoryStep(
        index=index,
        kind=kind,
        timestamp=_num(obj.get("timestamp")),
        command=command if isinstance(command, str) else None,
        path=path if isinstance(path, str) else None,
        exit_code=exit_code if isinstance(exit_code, int) else None,
        duration=_num(seen.get("duration")),
        timed_out=bool(seen.get("timed_out", False)),
        truncated=bool(seen.get("truncated", False)) or out_cut or err_cut or content_cut,
        stdout=stdout,
        stderr=stderr,
        flagged=tuple(dict.fromkeys(flags.get(index, ()))),
        content=content,
    )
