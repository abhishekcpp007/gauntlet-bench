"""What the terminal viewer shows: plain records, and the read-only source they come from.

Screens depend on `DataSource` only. `gauntlet.tui.store.Store` builds these records from the
shipped datasets and from run folders, using the harness's own code for every number. Nothing here
grades, writes or changes a score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

Verdict = Literal["clean", "suspicious", "cheating"]
Severity = Literal["low", "medium", "high"]
PolicyKind = Literal["oracle", "noop", "cheat", "model"]
Category = Literal["swe", "lht"]
Detail = Literal["full", "summary"]
RunKind = Literal["shipped", "folder"]
TestClass = Literal["f2p", "n2p", "s2p", "p2p"]
TestStatusName = Literal["PASSED", "FAILED", "SKIPPED", "NONE"]
HitKind = Literal["task", "episode", "run", "dataset"]


class NotFound(LookupError):
    """The id isn't in anything that was loaded."""


@dataclass(frozen=True, slots=True)
class Facet:
    id: str
    count: int


@dataclass(frozen=True, slots=True)
class Counts:
    passed: int
    failed: int
    skipped: int
    total: int


@dataclass(frozen=True, slots=True)
class Interval:
    value: float
    low: float
    high: float


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    id: str
    title: str
    tasks: int
    repos: int
    categories: tuple[Facet, ...]
    runners: tuple[Facet, ...]
    merged_from: str | None
    merged_to: str | None
    f2p_total: int
    n2p_total: int
    s2p_total: int
    p2p_total: int
    leakcheck_ok: int
    has_validation: bool


@dataclass(frozen=True, slots=True)
class DatasetDetail:
    summary: DatasetSummary
    by_repo: tuple[Facet, ...]
    prs_collected: int | None
    rejected_by_stage: tuple[Facet, ...]


@dataclass(frozen=True, slots=True)
class HorizonSummary:
    from_ref: str
    to_ref: str
    prs: int
    milestones: int


@dataclass(frozen=True, slots=True)
class TaskRow:
    instance_id: str
    dataset_id: str
    repo: str
    category: Category
    runner: str
    language: str
    pr_number: int | None
    pr_title: str
    pr_url: str | None
    merged_at: str | None
    f2p: int
    n2p: int
    s2p: int
    p2p: int
    flaky: int
    statement_source: str
    leakcheck_ok: bool
    horizon: HorizonSummary | None


@dataclass(frozen=True, slots=True)
class TaskFacets:
    datasets: tuple[Facet, ...]
    repos: tuple[Facet, ...]
    categories: tuple[Facet, ...]
    runners: tuple[Facet, ...]


@dataclass(frozen=True, slots=True)
class LeakCheck:
    id: str
    label: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class LinkedPR:
    number: int
    title: str
    url: str | None


@dataclass(frozen=True, slots=True)
class Milestone:
    id: str
    title: str
    tests: int


@dataclass(frozen=True, slots=True)
class HorizonDetail:
    from_ref: str
    to_ref: str
    prs: tuple[LinkedPR, ...]
    direct_commits: tuple[str, ...]
    milestones: tuple[Milestone, ...]
    dropped_regressions: tuple[str, ...]
    gold_lines: int


@dataclass(frozen=True, slots=True)
class ValidationRuns:
    run: Counts
    test: Counts
    fix: tuple[Counts, ...]
    fix_runs: int
    scope: str | None
    seconds_total: float | None


@dataclass(frozen=True, slots=True)
class EpisodeRow:
    run_id: str
    episode_id: str
    instance_id: str
    policy: str
    policy_kind: PolicyKind
    category: Category
    reward: float
    resolved: bool
    cheat_verdict: Verdict
    detail: Detail
    attempt: int | None = None
    tampered: bool | None = None
    steps: int | None = None
    seconds: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TaskDetail:
    row: TaskRow
    problem_statement: str
    image: str
    env_fingerprint: str
    base_commit: str
    solution_commit: str
    workdir: str
    test_files: tuple[str, ...]
    test_scope: tuple[str, ...]
    f2p: tuple[str, ...]
    n2p: tuple[str, ...]
    s2p: tuple[str, ...]
    flaky: tuple[str, ...]
    validation: ValidationRuns | None
    leakcheck_ok: bool
    leakchecks: tuple[LeakCheck, ...]
    gold_patch: str
    test_patch: str
    horizon: HorizonDetail | None
    episodes: tuple[EpisodeRow, ...]
    gold_patch_truncated: bool = False
    test_patch_truncated: bool = False


@dataclass(frozen=True, slots=True)
class PolicyGroup:
    """How one kind of policy did across a run: the oracle, noop, or all the cheats together."""

    episodes: int
    resolved: int
    min_reward: float
    max_reward: float
    cheating_verdicts: int


@dataclass(frozen=True, slots=True)
class RunSummary:
    id: str
    title: str
    kind: RunKind
    detail: Detail
    episodes: int
    tasks: int
    policies: tuple[str, ...]
    dataset_id: str | None = None
    path: str | None = None
    ran_from: str | None = None
    ran_to: str | None = None
    oracle: PolicyGroup | None = None
    noop: PolicyGroup | None = None
    cheats: PolicyGroup | None = None
    violations: int | None = None


@dataclass(frozen=True, slots=True)
class VerdictCounts:
    clean: int
    suspicious: int
    cheating: int


@dataclass(frozen=True, slots=True)
class PolicyRow:
    policy: str
    kind: PolicyKind
    episodes: int
    tasks: int
    resolved: int
    mean_reward: float
    min_reward: float
    max_reward: float
    verdicts: VerdictCounts
    errors: int
    pass_at_1: Interval | None = None
    tampered: int | None = None
    category: Category | None = None


@dataclass(frozen=True, slots=True)
class RunDetail:
    summary: RunSummary
    policies: tuple[PolicyRow, ...]
    calibration_checked: bool
    violations: tuple[str, ...]
    rotted: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class MatrixTask:
    instance_id: str
    repo: str
    category: Category


@dataclass(frozen=True, slots=True)
class MatrixCell:
    episode_id: str
    reward: float
    resolved: bool
    verdict: Verdict
    tampered: bool | None = None


@dataclass(frozen=True, slots=True)
class Matrix:
    """`cells[task_index][policy_index]`, None where that pair wasn't played."""

    policies: tuple[str, ...]
    tasks: tuple[MatrixTask, ...]
    cells: tuple[tuple[MatrixCell | None, ...], ...]


@dataclass(frozen=True, slots=True)
class EpisodeFacets:
    policies: tuple[Facet, ...]
    verdicts: tuple[Facet, ...]
    tasks: tuple[Facet, ...]


@dataclass(frozen=True, slots=True)
class RewardBreakdown:
    tests: float
    rubric: float
    similarity: float
    penalty: float
    w_tests: float | None = None
    w_rubric: float | None = None
    w_similarity: float | None = None
    capped_from: float | None = None
    milestones_done: int | None = None


@dataclass(frozen=True, slots=True)
class ClassCounts:
    total: int
    passed: int
    failed: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GradeDetail:
    patch_applied: bool
    resolved: bool
    error: str | None
    ignored_files: tuple[str, ...]
    compile_errors: tuple[str, ...]
    tampered: tuple[str, ...]
    milestones: tuple[tuple[str, float], ...]
    f2p: ClassCounts
    n2p: ClassCounts
    s2p: ClassCounts
    p2p: ClassCounts
    status_counts: tuple[Facet, ...]


@dataclass(frozen=True, slots=True)
class RubricItem:
    id: str
    category: str
    kind: str
    met: bool
    score: float
    rationale: str


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    severity: Severity
    message: str
    step: int | None
    file: str | None
    evidence: str


@dataclass(frozen=True, slots=True)
class Provenance:
    harness_version: str
    image: str
    env_fingerprint: str
    grading_seed: str | None
    ran_at: str
    policy_params: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class EpisodeDetail:
    row: EpisodeRow
    reward_breakdown: RewardBreakdown | None
    grade: GradeDetail | None
    rubric_score: float | None
    rubric_items: tuple[RubricItem, ...]
    rubric_skipped: tuple[str, ...]
    findings: tuple[Finding, ...]
    patch: str | None
    provenance: Provenance | None
    usage: tuple[tuple[str, str], ...]
    truncated: bool | None
    trajectory_steps: int | None
    patch_truncated: bool = False
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class TestStatus:
    id: str
    status: TestStatusName
    test_class: TestClass | None

    __test__ = False


@dataclass(frozen=True, slots=True)
class TrajectoryHeader:
    image: str
    sandbox_id: str
    created_at: float | None
    network: bool
    memory: str | None
    cpus: float | None


@dataclass(frozen=True, slots=True)
class TrajectoryStep:
    index: int
    kind: str
    timestamp: float | None
    command: str | None
    path: str | None
    exit_code: int | None
    duration: float | None
    timed_out: bool
    truncated: bool
    stdout: str
    stderr: str
    flagged: tuple[str, ...] = ()
    content: str = ""


@dataclass(frozen=True, slots=True)
class Trajectory:
    header: TrajectoryHeader | None
    steps: tuple[TrajectoryStep, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    id: str
    title: str
    what: str
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class Thresholds:
    oracle_min_reward: float
    noop_reward: float
    cheat_max_reward: float


@dataclass(frozen=True, slots=True)
class Reference:
    grading_steps: tuple[ReferenceItem, ...]
    leak_checks: tuple[ReferenceItem, ...]
    rules: tuple[ReferenceItem, ...]
    policies: tuple[ReferenceItem, ...]
    thresholds: Thresholds


@dataclass(frozen=True, slots=True)
class Totals:
    tasks: int
    repos: int
    datasets: int
    runs: int
    episodes: int
    leak_checks_per_task: int
    leak_check_failures: int
    cheat_policies: int
    cheatcatcher_rules: int


@dataclass(frozen=True, slots=True)
class Overview:
    version: str
    totals: Totals
    datasets: tuple[DatasetSummary, ...]
    runs: tuple[RunSummary, ...]
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class SearchHit:
    kind: HitKind
    id: str
    title: str
    subtitle: str
    run_id: str | None = None


class DataSource(Protocol):
    """Everything a screen can ask for. Every method is read-only and raises `NotFound` for an
    id that wasn't loaded."""

    def overview(self) -> Overview: ...

    def reference(self) -> Reference: ...

    def datasets(self) -> tuple[DatasetSummary, ...]: ...

    def dataset(self, dataset_id: str) -> DatasetDetail: ...

    def task_facets(self) -> TaskFacets: ...

    def tasks(
        self,
        *,
        dataset: str | None = None,
        repo: str | None = None,
        category: str | None = None,
        runner: str | None = None,
        query: str = "",
    ) -> tuple[TaskRow, ...]: ...

    def task(self, instance_id: str) -> TaskDetail: ...

    def task_tests(self, instance_id: str, test_class: TestClass, *, query: str = "") -> tuple[str, ...]: ...

    def runs(self) -> tuple[RunSummary, ...]: ...

    def run(self, run_id: str) -> RunDetail: ...

    def matrix(self, run_id: str) -> Matrix: ...

    def episode_facets(self, run_id: str) -> EpisodeFacets: ...

    def episodes(
        self,
        run_id: str,
        *,
        policy: str | None = None,
        task: str | None = None,
        verdict: str | None = None,
        resolved: bool | None = None,
        query: str = "",
    ) -> tuple[EpisodeRow, ...]: ...

    def episode(self, run_id: str, episode_id: str) -> EpisodeDetail: ...

    def episode_tests(
        self,
        run_id: str,
        episode_id: str,
        *,
        test_class: TestClass | None = None,
        status: str | None = None,
        query: str = "",
    ) -> tuple[TestStatus, ...]: ...

    def trajectory(self, run_id: str, episode_id: str) -> Trajectory | None: ...

    def search(self, query: str, *, limit: int) -> tuple[SearchHit, ...]: ...
