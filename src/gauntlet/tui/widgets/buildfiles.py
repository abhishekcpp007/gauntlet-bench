"""What a finished "Make tasks" job kept and why it rejected the rest, read from the files it wrote.

`gauntlet build` and `gauntlet build-lht` write one `HarnessTask` per line to `tasks.jsonl` and one
`Rejected` (an id, a stage and a reason) per line to `rejected.jsonl`, and `gauntlet collect` writes
one `PRInfo` per line to `prs.jsonl`. `read_build` turns them into a `BuildSummary`: how many PRs or
release ranges went in, the tasks that came out, and every rejection with its PR number and title.

Plain Python, no Textual and no harness import (the harness's builders pull in Docker). A line that
isn't a JSON object is counted in `skipped`, never raised, since a job may have stopped mid-write.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import format as fmt
from ..jobtypes import JobSpec

PR_UNIT = "PR"
RANGE_UNIT = "release range"
RANGE_FLAG = "--range"
REPO_FLAG = "--repo"
RANGE_SEPARATOR = ".."
UNSAFE_REF = re.compile(r"[^A-Za-z0-9.]+")
REPO_SEPARATOR = "__"


@dataclass(frozen=True, slots=True)
class Item:
    """One PR or release range: what it's called (`#475`, `v1.2.0..v1.3.0`), a line about it, and
    for a rejection the stage it stopped at and the harness's reason."""

    id: str
    name: str
    title: str = ""
    stage: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class BuildSummary:
    """`asked` is how many PRs were collected (or ranges asked for), None when that file is gone.
    `missing` names the files the job never wrote."""

    unit: str
    asked: int | None
    kept: tuple[Item, ...]
    rejected: tuple[Item, ...]
    skipped: int = 0
    missing: tuple[str, ...] = ()

    @property
    def looked_at(self) -> int:
        return len(self.kept) + len(self.rejected)

    @property
    def finished(self) -> bool:
        """Whether the build got through everything it was given."""
        return self.asked is not None and self.looked_at >= self.asked

    def stages(self) -> tuple[tuple[str, tuple[Item, ...]], ...]:
        """The rejections grouped by stage, the biggest group first."""
        groups: dict[str, list[Item]] = {}
        for item in self.rejected:
            groups.setdefault(item.stage, []).append(item)
        return tuple(sorted(((s, tuple(i)) for s, i in groups.items()), key=lambda g: (-len(g[1]), g[0])))


def pr_instance_id(repo: str, number: object) -> str:
    """The id `gauntlet build` gives a PR's task or rejection, as `harness.build.instance_id` does."""
    owner, _, name = repo.partition("/")
    return f"{owner}{REPO_SEPARATOR}{name}-{number}"


def range_instance_id(repo: str, from_ref: str, to_ref: str) -> str:
    """The id `gauntlet build-lht` gives a range's task or rejection, as `harness.lht.range_id` does."""
    owner, _, name = repo.partition("/")

    def clean(ref: str) -> str:
        return UNSAFE_REF.sub("-", ref).strip("-")

    return f"{owner}{REPO_SEPARATOR}{name}-{clean(from_ref)}_to_{clean(to_ref)}"


def read_rows(path: Path) -> tuple[list[dict[str, object]], int]:
    """Every JSON object in a `.jsonl` file, and how many lines weren't one."""
    rows: list[dict[str, object]] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped


def _text(row: Mapping[str, object], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value)


def _flag_values(argv: Sequence[str], flag: str) -> list[str]:
    return [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == flag]


def _output(spec: JobSpec, kind: str) -> Path | None:
    return next((Path(o.path) for o in spec.outputs if o.kind == kind), None)


class _Files:
    """The rows of the files a spec names, with what was skipped or missing on the way."""

    def __init__(self, spec: JobSpec) -> None:
        self.skipped = 0
        self.missing: list[str] = []
        self.spec = spec

    def rows(self, kind: str) -> list[dict[str, object]] | None:
        path = _output(self.spec, kind)
        if path is None:
            return None
        try:
            rows, skipped = read_rows(path)
        except FileNotFoundError:
            self.missing.append(path.name)
            return None
        self.skipped += skipped
        return rows


def read_build(spec: JobSpec) -> BuildSummary:
    """What a `make_tasks` or `make_lht_tasks` job wrote, from the outputs its spec names."""
    if spec.action == "make_lht_tasks":
        return _read_ranges(spec)
    return _read_prs(spec)


def _read_prs(spec: JobSpec) -> BuildSummary:
    files = _Files(spec)
    prs = files.rows("prs")
    tasks = files.rows("tasks") or []
    rejected = files.rows("rejected") or []
    repos = {_text(pr, "repo") for pr in prs or ()}
    many = len(repos) > 1

    def named(repo: str, number: object) -> str:
        return f"{repo}#{number}" if many else f"#{number}"

    known: dict[str, Item] = {}
    for pr in prs or ():
        repo, number = _text(pr, "repo"), pr.get("number")
        iid = pr_instance_id(repo, number)
        known[iid] = Item(iid, named(repo, number), fmt.one_line(_text(pr, "title")))
    kept = []
    for task in tasks:
        iid = _text(task, "instance_id")
        pr = task.get("pr")
        title = fmt.one_line(_text(pr, "title")) if isinstance(pr, dict) else ""
        number = pr.get("number") if isinstance(pr, dict) else None
        fallback = Item(iid, named(_text(pr, "repo"), number) if number is not None else iid, title)
        kept.append(known.get(iid, fallback))
    dropped = []
    for row in rejected:
        iid = _text(row, "instance_id")
        base = known.get(iid, Item(iid, iid))
        dropped.append(
            Item(iid, base.name, base.title, _text(row, "stage"), fmt.one_line(_text(row, "reason")))
        )
    return BuildSummary(
        unit=PR_UNIT,
        asked=None if prs is None else len(prs),
        kept=tuple(kept),
        rejected=tuple(dropped),
        skipped=files.skipped,
        missing=tuple(files.missing),
    )


def _read_ranges(spec: JobSpec) -> BuildSummary:
    files = _Files(spec)
    tasks = files.rows("tasks") or []
    rejected = files.rows("rejected") or []
    argv = spec.steps[0].argv if spec.steps else ()
    repo = next(iter(_flag_values(argv, REPO_FLAG)), "")
    asked = _flag_values(argv, RANGE_FLAG)
    known: dict[str, str] = {}
    for value in asked:
        a, _, b = value.partition(RANGE_SEPARATOR)
        known[range_instance_id(repo, a, b)] = value
    kept = []
    for task in tasks:
        iid = _text(task, "instance_id")
        horizon = task.get("horizon")
        if isinstance(horizon, dict):
            name = f"{_text(horizon, 'from_ref')}{RANGE_SEPARATOR}{_text(horizon, 'to_ref')}"
            prs, milestones = horizon.get("prs"), horizon.get("milestones")
            title = ", ".join(
                fmt.plural(len(values), word)
                for values, word in ((prs, "PR"), (milestones, "milestone"))
                if isinstance(values, list)
            )
        else:
            name, title = known.get(iid, iid), ""
        kept.append(Item(iid, name, title))
    dropped = [
        Item(
            _text(row, "instance_id"),
            known.get(_text(row, "instance_id"), _text(row, "instance_id")),
            stage=_text(row, "stage"),
            reason=fmt.one_line(_text(row, "reason")),
        )
        for row in rejected
    ]
    return BuildSummary(
        unit=RANGE_UNIT,
        asked=len(asked) if asked else None,
        kept=tuple(kept),
        rejected=tuple(dropped),
        skipped=files.skipped,
        missing=tuple(files.missing),
    )
