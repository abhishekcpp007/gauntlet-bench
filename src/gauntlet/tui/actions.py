"""Every Workbench action as a typed builder that returns a `JobSpec`.

A builder takes plain values, checks them, and builds the exact `gauntlet` command lines a person
would type, with the flags and defaults from `gauntlet.harness.cli`. Anything wrong raises one
`ActionError` with a message a form can show next to the field. Nothing here runs a command, and
the only one that writes is `try_patch`, which copies one task into its run folder.

Every output goes inside the workspace. Inputs (a task set, a patch) can live anywhere and are
passed on as absolute paths, so the command means the same thing from any folder.

`ACTIONS` lists the actions in the order the Workbench shows them. `list_ranges` is the first
half of "From a release range", so it isn't in that list. Two jobs answer in their log rather
than in a file: `parse_ranges` reads what `list_ranges` printed, and `parse_scan` reads what
"Scan a patch" printed.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from gauntlet.cheatcatcher.cli import EXIT_CODES as SCAN_EXIT_CODES
from gauntlet.cheatcatcher.models import Report as ScanReport
from gauntlet.harness.budget import parse_prices
from gauntlet.harness.cli import CALIBRATION_POLICIES
from gauntlet.harness.policies import PATCH_PREFIX, ClaudePolicy, make_policy

from .jobtypes import ActionInfo, JobSpec, Need, Output, Step
from .models import Finding, Verdict
from .workspace import PRS_FILE, REJECTED_FILE, TASKS_FILE, Kind, Workspace, WorkspaceError, check_name

ONE_TASK_FILE = "task.jsonl"
HTML_SUFFIX = ".html"

# The harness's own defaults, from gauntlet.harness.cli. tests/tui/test_actions.py parses each
# builder's command with the real parser and checks these against it.
COLLECT_LIMIT = 30
PYTHON = "3.12"
SCOPES = ("full", "changed")
SCOPE = "full"
FIX_RUNS = 2
LHT_MAX_PRS = 40
LHT_MAX_GOLD_LINES = 6000
ATTEMPTS = 1
WORKERS = 2
SAMPLE_ALL = 0
CATEGORIES = ("swe", "lht")
TRY_PATCH_ATTEMPT = 0
TRY_PATCH_WORKERS = 1

MAX_LIMIT = 1000
MAX_FIX_RUNS = 10
MAX_WORKERS = 32
MAX_ATTEMPTS = 100
MAX_SAMPLE = 100_000
MAX_LAST = 1000
MAX_STEPS = 10_000
MAX_LHT_PRS = 1000
MAX_GOLD_LINES = 1_000_000

REPO_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
PYTHON_PATTERN = re.compile(r"\d+\.\d+")
REF_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+-]*")
WORD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]*")
REPO_PATH_PATTERN = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*")
RANGE_SEPARATOR = ".."
URL_PREFIXES = ("https://", "http://", "git@", "ssh://", "file://")
RANGE_LINE = re.compile(r"(?P<a>[^\t]+)\t(?P<b>[^\t]+)\t(?P<prs>\d+) PRs\t(?P<direct>\d+) direct commits")

SANDBOX: tuple[Need, ...] = ("docker", "network")
NETWORK: tuple[Need, ...] = ("network",)


class ActionError(ValueError):
    """An input that can't be used. The message says which one and why, in plain words."""


ACTIONS: tuple[ActionInfo, ...] = (
    ActionInfo(
        "make_tasks",
        "From fresh PRs",
        "make",
        "Collects recently merged PRs and builds a leak-checked task from each. Docker and network, "
        "a few minutes a PR.",
        SANDBOX,
    ),
    ActionInfo(
        "make_lht_tasks",
        "From a release range",
        "make",
        "Turns the work between two releases into one long task. Docker and network, and it can "
        "take an hour.",
        SANDBOX,
    ),
    ActionInfo(
        "leakcheck",
        "Leak check",
        "check",
        "Runs the 8 leak checks again on a task set, in a sandbox. Docker and network.",
        SANDBOX,
    ),
    ActionInfo(
        "check_envs",
        "Check env fingerprints",
        "check",
        "Recomputes each task's env fingerprint so drift shows up before a rebuild. Clones each repo, "
        "no Docker.",
        NETWORK,
    ),
    ActionInfo(
        "calibrate",
        "Calibrate",
        "check",
        "Pits the real fix and a blank answer against the 9 cheats and checks the grader scores "
        "them right. Docker, and it takes a while.",
        SANDBOX,
    ),
    ActionInfo(
        "run_policies",
        "Run policies",
        "score",
        "Grades the oracle, noop, cheats, a Claude model or your patch on a task set. Docker, and a "
        "key for Claude.",
        SANDBOX,
    ),
    ActionInfo(
        "try_patch",
        "Try a patch",
        "score",
        "Grades your own patch on one task, the way an agent's patch is graded, then opens the "
        "episode. Docker.",
        SANDBOX,
    ),
    ActionInfo(
        "scan_patch",
        "Scan a patch",
        "score",
        "Runs Cheat Catcher's rules over a patch and says if it looks like cheating. No Docker, it "
        "takes a second.",
    ),
    ActionInfo(
        "report",
        "Report",
        "score",
        "Prints a run's leaderboard with pass rates and their intervals. It can write an HTML page too.",
    ),
)


@dataclass(frozen=True, slots=True)
class ReleaseRange:
    """One line of `gauntlet ranges`: a release and the newest earlier release it builds on."""

    from_ref: str
    to_ref: str
    prs: int
    direct_commits: int

    @property
    def spec(self) -> str:
        """`FROM..TO`, the way `build-lht --range` takes it."""
        return f"{self.from_ref}{RANGE_SEPARATOR}{self.to_ref}"


@dataclass(frozen=True, slots=True)
class ScanResult:
    """What `cheatcatcher scan --json` found."""

    verdict: Verdict
    findings: tuple[Finding, ...]


# ---------------------------------------------------------------------- checks


def check_repo(repo: str) -> str:
    """`owner/name`, as on GitHub."""
    repo = repo.strip()
    if not REPO_PATTERN.fullmatch(repo):
        raise ActionError(f"{repo!r} isn't a repo. Write it as owner/name, for example pallets/click")
    return repo


def check_date(value: str) -> str:
    """A real calendar date written `YYYY-MM-DD`."""
    value = value.strip()
    try:
        if not DATE_PATTERN.fullmatch(value):
            raise ValueError
        date.fromisoformat(value)
    except ValueError:
        raise ActionError(f"{value!r} isn't a date. Write it as YYYY-MM-DD, for example 2026-06-01") from None
    return value


def check_int(what: str, value: int, low: int, high: int) -> int:
    """A whole number from `low` to `high`, both included."""
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ActionError(f"{what} must be a whole number from {low} to {high}, not {value!r}")
    return value


def check_positive(what: str, value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ActionError(f"{what} must be a number above 0, not {value!r}")
    return value


def check_choice(what: str, value: str, choices: Sequence[str]) -> str:
    if value not in choices:
        raise ActionError(f"{what} must be one of {', '.join(choices)}, not {value!r}")
    return value


def check_python(version: str) -> str:
    if not PYTHON_PATTERN.fullmatch(version):
        raise ActionError(f"{version!r} isn't a Python version. Write it like 3.12")
    return version


def check_file(what: str, path: Path | str) -> Path:
    """An existing file, as an absolute path."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ActionError(f"{what} {path} doesn't exist or isn't a file")
    return resolved


def check_word(what: str, value: str) -> str:
    """A short value that can't be mistaken for a flag: a seed, a test path to protect."""
    if not WORD_PATTERN.fullmatch(value):
        raise ActionError(f"{what} {value!r} can only hold letters, digits, '_', '.', ':' and '-'")
    return value


def check_repo_path(path: str) -> str:
    """A path inside a repo, like `tests/test_x.py`."""
    if not REPO_PATH_PATTERN.fullmatch(path) or ".." in path.split("/"):
        raise ActionError(f"{path!r} isn't a path inside the repo, like tests/test_x.py")
    return path


def check_ref(ref: str) -> str:
    if RANGE_SEPARATOR in ref or not REF_PATTERN.fullmatch(ref):
        raise ActionError(f"{ref!r} isn't a release tag")
    return ref


def check_repo_url(url: str) -> str:
    """A git URL, or a local clone, which is passed on as an absolute path."""
    if url.startswith(URL_PREFIXES):
        return url
    path = Path(url).expanduser()
    if path.is_dir():
        return str(path.resolve())
    raise ActionError(f"{url!r} isn't a git URL or a folder on this machine")


def check_policies(policies: Sequence[str] | str) -> tuple[str, ...]:
    """Policy specs the harness accepts, checked by `make_policy` itself.

    A `patch:` path is made absolute. A spec with a comma is refused, since `--policies` splits
    on commas.
    """
    raw = policies.split(",") if isinstance(policies, str) else list(policies)
    specs: list[str] = []
    for spec in (p.strip() for p in raw):
        if not spec:
            continue
        if "," in spec:
            raise ActionError(f"{spec!r} has a comma, which --policies can't carry")
        if spec.startswith(PATCH_PREFIX):
            spec = f"{PATCH_PREFIX}{check_file('The patch file', spec.removeprefix(PATCH_PREFIX))}"
        try:
            make_policy(spec)
        except ValueError as e:
            raise ActionError(str(e) if spec in str(e) else f"{spec}: {e}") from None
        specs.append(spec)
    if not specs:
        raise ActionError("Pick at least one policy")
    return tuple(specs)


def needs_api_key(policies: Sequence[str]) -> bool:
    """True when a policy calls Claude, which the harness decides."""
    return any(isinstance(make_policy(spec), ClaudePolicy) for spec in policies)


def _name(workspace: Workspace, kind: Kind, name: str | None, label: str) -> str:
    if name is None:
        return workspace.new_name(kind, label)
    try:
        return check_name(name)
    except WorkspaceError as e:
        raise ActionError(str(e)) from None


def _sandbox_needs(policies: Sequence[str]) -> tuple[Need, ...]:
    return (*SANDBOX, "api_key") if needs_api_key(policies) else SANDBOX


def _optional(flag: str, value: object | None) -> tuple[str, ...]:
    return () if value is None else (flag, str(value))


# ---------------------------------------------------------------------- make tasks


def make_tasks(
    workspace: Workspace,
    repos: Sequence[str],
    *,
    merged_after: str | None = None,
    limit: int = COLLECT_LIMIT,
    scope: str = SCOPE,
    fix_runs: int = FIX_RUNS,
    python: str = PYTHON,
    git_fallback: bool = False,
    name: str | None = None,
) -> JobSpec:
    """`collect` the repos' merged PRs into `tasks/<name>/prs.jsonl`, then `build` them into
    `tasks.jsonl`, with every rejection and its reason in `rejected.jsonl`."""
    checked = tuple(check_repo(r) for r in repos)
    if not checked:
        raise ActionError("Add at least one repo")
    after = check_date(merged_after) if merged_after else None
    check_int("The PR limit", limit, 1, MAX_LIMIT)
    check_choice("The test scope", scope, SCOPES)
    check_int("Fix runs", fix_runs, 1, MAX_FIX_RUNS)
    check_python(python)
    folder = workspace.path_for("tasks", _name(workspace, "tasks", name, checked[0]))
    prs, tasks, rejected = folder / PRS_FILE, folder / TASKS_FILE, folder / REJECTED_FILE
    collect = (
        "collect",
        *(arg for repo in checked for arg in ("--repo", repo)),
        *_optional("--merged-after", after),
        "--limit",
        str(limit),
        *(("--git-fallback",) if git_fallback else ()),
        "-o",
        str(prs),
    )
    build = (
        "build",
        "--prs",
        str(prs),
        "-o",
        str(tasks),
        "--rejected",
        str(rejected),
        "--python",
        python,
        "--scope",
        scope,
        "--fix-runs",
        str(fix_runs),
    )
    return JobSpec(
        action="make_tasks",
        title=f"Make tasks from {', '.join(checked)}",
        steps=(Step("Collect merged PRs", collect), Step("Build and leak-check tasks", build)),
        needs=SANDBOX,
        outputs=(
            Output("tasks", str(tasks), "Tasks"),
            Output("rejected", str(rejected), "Rejected PRs"),
            Output("prs", str(prs), "Collected PRs"),
        ),
    )


def list_ranges(
    repo: str, *, repo_url: str | None = None, last: int | None = None, prereleases: bool = False
) -> JobSpec:
    """`ranges`: the release ranges a repo offers. Read its log with `parse_ranges`."""
    repo = check_repo(repo)
    url = check_repo_url(repo_url) if repo_url else None
    if last is not None:
        check_int("Newest ranges", last, 1, MAX_LAST)
    argv = (
        "ranges",
        "--repo",
        repo,
        *_optional("--repo-url", url),
        *_optional("--last", last),
        *(("--prereleases",) if prereleases else ()),
    )
    return JobSpec(
        action="list_ranges",
        title=f"List release ranges of {repo}",
        steps=(Step("List release ranges", argv),),
        needs=() if url and not url.startswith(URL_PREFIXES) else NETWORK,
        exclusive=False,
    )


def parse_ranges(lines: Sequence[str]) -> tuple[ReleaseRange, ...]:
    """The ranges in `gauntlet ranges` output (`FROM<tab>TO<tab>N PRs<tab>M direct commits`).
    Other lines, like progress on stderr, are skipped."""
    found = []
    for line in lines:
        if m := RANGE_LINE.fullmatch(line.rstrip("\r\n")):
            found.append(ReleaseRange(m["a"], m["b"], int(m["prs"]), int(m["direct"])))
    return tuple(found)


def _range_spec(value: ReleaseRange | str) -> str:
    if isinstance(value, ReleaseRange):
        a, b = value.from_ref, value.to_ref
    else:
        a, sep, b = value.partition(RANGE_SEPARATOR)
        if not sep:
            raise ActionError(f"{value!r} isn't a range. Write it as FROM..TO, for example v1.2.0..v1.3.0")
    return f"{check_ref(a)}{RANGE_SEPARATOR}{check_ref(b)}"


def make_lht_tasks(
    workspace: Workspace,
    repo: str,
    *,
    ranges: Sequence[ReleaseRange | str] = (),
    last: int | None = None,
    repo_url: str | None = None,
    python: str = PYTHON,
    fix_runs: int = FIX_RUNS,
    max_prs: int = LHT_MAX_PRS,
    max_gold_lines: int = LHT_MAX_GOLD_LINES,
    scope: str = SCOPE,
    name: str | None = None,
) -> JobSpec:
    """`build-lht` into `tasks/<name>/`. With no `ranges`, every range (or the newest `last`)."""
    repo = check_repo(repo)
    specs = tuple(_range_spec(r) for r in ranges)
    if last is not None:
        check_int("Newest ranges", last, 1, MAX_LAST)
    url = check_repo_url(repo_url) if repo_url else None
    check_python(python)
    check_int("Fix runs", fix_runs, 1, MAX_FIX_RUNS)
    check_int("Max PRs", max_prs, 1, MAX_LHT_PRS)
    check_int("Max gold lines", max_gold_lines, 1, MAX_GOLD_LINES)
    check_choice("The test scope", scope, SCOPES)
    folder = workspace.path_for("tasks", _name(workspace, "tasks", name, f"{repo}-lht"))
    tasks, rejected = folder / TASKS_FILE, folder / REJECTED_FILE
    argv = (
        "build-lht",
        "--repo",
        repo,
        *_optional("--repo-url", url),
        *(arg for spec in specs for arg in ("--range", spec)),
        *(() if specs else _optional("--last", last)),
        "-o",
        str(tasks),
        "--rejected",
        str(rejected),
        "--python",
        python,
        "--fix-runs",
        str(fix_runs),
        "--max-prs",
        str(max_prs),
        "--max-gold-lines",
        str(max_gold_lines),
        "--scope",
        scope,
    )
    return JobSpec(
        action="make_lht_tasks",
        title=f"Make long tasks from {repo}",
        steps=(Step("Build long tasks from release ranges", argv),),
        needs=SANDBOX,
        outputs=(Output("tasks", str(tasks), "Tasks"), Output("rejected", str(rejected), "Rejected ranges")),
    )


# ---------------------------------------------------------------------- check


def leakcheck(tasks_file: Path | str) -> JobSpec:
    """`leakcheck`: the 8 leak checks again. Exits 1 when a task leaks, which fails the job."""
    tasks = check_file("The task file", tasks_file)
    return JobSpec(
        action="leakcheck",
        title=f"Leak check {tasks.parent.name}/{tasks.name}",
        steps=(Step("Leak check every task", ("leakcheck", "--tasks", str(tasks))),),
        needs=SANDBOX,
    )


def check_envs(tasks_files: Sequence[Path | str]) -> JobSpec:
    """`check-envs`: recompute each task's env fingerprint. Exits 1 on drift, which fails the job."""
    files = tuple(str(check_file("The task file", f)) for f in tasks_files)
    if not files:
        raise ActionError("Pick at least one task file")
    return JobSpec(
        action="check_envs",
        title=f"Check env fingerprints in {len(files)} task file(s)",
        steps=(Step("Recompute env fingerprints", ("check-envs", "--tasks", *files)),),
        needs=NETWORK,
        exclusive=False,
    )


def calibrate(
    workspace: Workspace,
    tasks_file: Path | str,
    *,
    sample: int = SAMPLE_ALL,
    seed: str | None = None,
    policies: Sequence[str] = CALIBRATION_POLICIES,
    workers: int = WORKERS,
    name: str | None = None,
) -> JobSpec:
    """`calibrate` into `runs/<name>/`. `sample` 0 means every task, and with no `seed` the
    harness uses today's date. Exits 1 on a violation, which fails the job: the run folder
    still holds every episode."""
    tasks = check_file("The task file", tasks_file)
    check_int("Sample", sample, SAMPLE_ALL, MAX_SAMPLE)
    if seed is not None:
        check_word("The seed", seed)
    specs = check_policies(policies)
    check_int("Workers", workers, 1, MAX_WORKERS)
    out = workspace.path_for("runs", _name(workspace, "runs", name, f"calibrate-{tasks.parent.name}"))
    argv = (
        "calibrate",
        "--tasks",
        str(tasks),
        "--sample",
        str(sample),
        *_optional("--seed", seed),
        "--policies",
        ",".join(specs),
        "--workers",
        str(workers),
        "-o",
        str(out),
    )
    return JobSpec(
        action="calibrate",
        title=f"Calibrate on {tasks.parent.name}",
        steps=(Step("Calibrate the grader", argv),),
        needs=_sandbox_needs(specs),
        outputs=(Output("run", str(out), "Calibration run"),),
    )


# ---------------------------------------------------------------------- score


def run_policies(
    workspace: Workspace,
    tasks_file: Path | str,
    policies: Sequence[str] | str,
    *,
    attempts: int = ATTEMPTS,
    workers: int = WORKERS,
    category: str | None = None,
    max_steps: int | None = None,
    max_episodes: int | None = None,
    max_tokens: int | None = None,
    max_seconds: float | None = None,
    max_usd: float | None = None,
    prices: str | None = None,
    name: str | None = None,
) -> JobSpec:
    """`run` into `runs/<name>/`. Leave a ceiling as None for none. `max_usd` needs `prices`,
    written the harness's way (`claude:=3/15`). A run folder that exists is carried on, which is
    how the harness resumes."""
    tasks = check_file("The task file", tasks_file)
    specs = check_policies(policies)
    check_int("Attempts", attempts, 1, MAX_ATTEMPTS)
    check_int("Workers", workers, 1, MAX_WORKERS)
    if category is not None:
        check_choice("The category", category, CATEGORIES)
    if max_steps is not None:
        check_int("Max steps", max_steps, 1, MAX_STEPS)
    for what, ceiling in (
        ("Max episodes", max_episodes),
        ("Max tokens", max_tokens),
        ("Max seconds", max_seconds),
        ("Max dollars", max_usd),
    ):
        if ceiling is not None:
            check_positive(what, ceiling)
    if prices is not None:
        try:
            parse_prices(prices)
        except ValueError as e:
            raise ActionError(f"Prices: {e}") from None
    if max_usd is not None and not prices:
        raise ActionError("Max dollars needs prices, for example claude:=3/15")
    out = workspace.path_for("runs", _name(workspace, "runs", name, tasks.parent.name))
    argv = (
        "run",
        "--tasks",
        str(tasks),
        *_optional("--category", category),
        "-o",
        str(out),
        "--policies",
        ",".join(specs),
        "--attempts",
        str(attempts),
        "--workers",
        str(workers),
        *_optional("--max-steps", max_steps),
        *_optional("--max-episodes", max_episodes),
        *_optional("--max-tokens", max_tokens),
        *_optional("--max-seconds", max_seconds),
        *_optional("--max-usd", max_usd),
        *_optional("--prices", prices),
    )
    return JobSpec(
        action="run_policies",
        title=f"Run {len(specs)} polic{'y' if len(specs) == 1 else 'ies'} on {tasks.parent.name}",
        steps=(Step("Run and grade every episode", argv),),
        needs=_sandbox_needs(specs),
        outputs=(Output("run", str(out), "Run"),),
    )


def _task_line(tasks_file: Path, instance_id: str) -> bytes:
    with tasks_file.open("rb") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                found = json.loads(line).get("instance_id")
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                continue
            if found == instance_id:
                return line
    raise ActionError(f"There's no task {instance_id!r} in {tasks_file}")


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def try_patch(
    workspace: Workspace,
    tasks_file: Path | str,
    instance_id: str,
    patch_file: Path | str,
    *,
    name: str | None = None,
) -> JobSpec:
    """`run` one task with `patch:<file>` into `runs/<name>/`.

    The task's line is copied byte for byte into `runs/<name>/task.jsonl`, which is the one
    thing a builder writes. The run output carries the episode id the runner will give it,
    worked out with `gauntlet.harness.runner.episode_id` itself, so the Workbench can open that
    episode as soon as the job succeeds.
    """
    from gauntlet.harness.runner import episode_id
    from gauntlet.harness.schema import HarnessTask

    tasks = check_file("The task file", tasks_file)
    patch = check_file("The patch file", patch_file)
    spec = check_policies([f"{PATCH_PREFIX}{patch}"])[0]
    line = _task_line(tasks, instance_id)
    try:
        task = HarnessTask.model_validate_json(line)
    except ValueError as e:
        raise ActionError(f"The line for {instance_id} in {tasks} isn't a task: {e}") from None
    out = workspace.path_for("runs", _name(workspace, "runs", name, f"try-{instance_id}"))
    one = workspace.run_dir(out.name) / ONE_TASK_FILE
    _write_atomic(one, line)
    argv = (
        "run",
        "--tasks",
        str(one),
        "-o",
        str(out),
        "--policies",
        spec,
        "--attempts",
        str(ATTEMPTS),
        "--workers",
        str(TRY_PATCH_WORKERS),
    )
    return JobSpec(
        action="try_patch",
        title=f"Try {patch.name} on {instance_id}",
        steps=(Step("Apply the patch and grade it", argv),),
        needs=SANDBOX,
        outputs=(
            Output("run", str(out), "Episode", episode_id=episode_id(task, spec, TRY_PATCH_ATTEMPT)),
            Output("tasks", str(one), "The task"),
        ),
    )


def scan_patch(
    patch_file: Path | str, *, protect: Sequence[str] = (), trajectory: Path | str | None = None
) -> JobSpec:
    """`cheatcatcher scan --patch <file> --json`, with no Docker. Exit 1 (suspicious) and 2
    (cheating) are a finished scan, so the job succeeds and keeps the code: read the verdict
    with `parse_scan` on the log."""
    patch = check_file("The patch file", patch_file)
    paths = tuple(check_repo_path(p) for p in protect)
    traj = check_file("The trajectory", trajectory) if trajectory is not None else None
    argv = (
        "cheatcatcher",
        "scan",
        "--patch",
        str(patch),
        *_optional("--trajectory", traj),
        *(("--protect", *paths) if paths else ()),
        "--json",
    )
    return JobSpec(
        action="scan_patch",
        title=f"Scan {patch.name}",
        steps=(Step("Scan the patch", argv, ok_codes=tuple(sorted(SCAN_EXIT_CODES.values()))),),
        exclusive=False,
    )


def parse_scan(text: str) -> ScanResult:
    """The report in a scan's output. Lines before the JSON, like a warning, are skipped."""
    start = text.find("{")
    if start < 0:
        raise ActionError("The scan printed no report")
    try:
        raw, _ = json.JSONDecoder().raw_decode(text, start)
        report = ScanReport.model_validate(raw)
    except ValueError as e:
        raise ActionError(f"The scan's report couldn't be read: {e}") from None
    findings = tuple(
        Finding(
            rule=f.rule, severity=f.severity, message=f.message, step=f.step, file=f.file, evidence=f.evidence
        )
        for f in report.findings
    )
    return ScanResult(verdict=report.verdict, findings=findings)


def report(
    workspace: Workspace,
    results_file: Path | str,
    *,
    cutoff: str | None = None,
    html: bool = False,
    name: str | None = None,
) -> JobSpec:
    """`report`: the leaderboard, printed to the log. With `html`, also `reports/<name>.html`,
    and the `reports/` folder is made now, since the harness writes the page without making it."""
    results = check_file("The results file", results_file)
    cut = check_date(cutoff) if cutoff else None
    page = None
    if html:
        page = (
            workspace.reports_dir() / f"{_name(workspace, 'reports', name, results.parent.name)}{HTML_SUFFIX}"
        )
    argv = ("report", "--results", str(results), *_optional("--cutoff", cut), *_optional("--html", page))
    return JobSpec(
        action="report",
        title=f"Report on {results.parent.name}",
        steps=(Step("Build the leaderboard", argv),),
        outputs=(Output("report", str(page), "HTML report"),) if page else (),
        exclusive=False,
    )
