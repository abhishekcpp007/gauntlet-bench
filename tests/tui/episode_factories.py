"""Extra sample episodes for the Episode screen tests: one per reward path, and the odd records."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from gauntlet.tui.models import (
    ClassCounts,
    EpisodeDetail,
    Facet,
    RewardBreakdown,
    TestStatus,
    Trajectory,
    TrajectoryHeader,
    TrajectoryStep,
)

from .factories import GOLDEN, FakeSource, make_episode_detail, make_episode_row, make_source

LHT_TASK = "jazzband__tablib-v3.8.0_to_v3.9.0"
HOSTILE_COMMAND = "echo '[red]boom[/red]' \x1b[2J && rm -rf /"
LONG_OUTPUT_LINES = 120
MANY_TESTS = 5000
LHT_STEPS = 400
FAILED_EVERY = 7
FLAGGED_EVERY = 50


def breakdown(**overrides: Any) -> RewardBreakdown:
    values: dict[str, Any] = {
        "tests": 1.0,
        "rubric": 0.85,
        "similarity": 1.0,
        "penalty": 0.0,
        "w_tests": 0.6,
        "w_rubric": 0.25,
        "w_similarity": 0.15,
    }
    values.update(overrides)
    return RewardBreakdown(**values)


def step(index: int, **overrides: Any) -> TrajectoryStep:
    values: dict[str, Any] = {
        "index": index,
        "kind": "exec",
        "timestamp": None,
        "command": f"echo step {index}",
        "path": None,
        "exit_code": 0,
        "duration": 0.2,
        "timed_out": False,
        "truncated": False,
        "stdout": f"step {index}",
        "stderr": "",
    }
    values.update(overrides)
    return TrajectoryStep(**values)


HEADER = TrajectoryHeader(
    image="gauntlet-harness-env:8b04a9c8ff22041c",
    sandbox_id="sbx-4f2a",
    created_at=None,
    network=False,
    memory="512m",
    cpus=1.0,
)


def trajectory(*steps: TrajectoryStep, warnings: tuple[str, ...] = ()) -> Trajectory:
    return Trajectory(header=HEADER, steps=steps, warnings=warnings)


def long_trajectory(count: int = LHT_STEPS) -> Trajectory:
    return trajectory(
        *(step(i, flagged=("answer-peeking",) if i and i % FLAGGED_EVERY == 0 else ()) for i in range(count))
    )


def odd_trajectory() -> Trajectory:
    """Every kind of step the sandbox records, with a hostile command and long output."""
    return trajectory(
        step(0, command=HOSTILE_COMMAND, stdout="\x1b[31m[bold]FAILED[/bold]\x1b[0m", exit_code=2),
        step(
            1, kind="write_file", command=None, path="conftest.py", content="import pytest\n", exit_code=None
        ),
        step(
            2, stdout="\n".join(f"line {n}" for n in range(LONG_OUTPUT_LINES)), timed_out=True, truncated=True
        ),
        step(3, kind="put_archive", command=None, exit_code=None, duration=None, stdout=""),
        step(4, flagged=("outcome-forcing", "conftest-hooks")),
        step(5, flagged=("shell-test-edit",)),
    )


def many_tests() -> tuple[TestStatus, ...]:
    return tuple(
        TestStatus(
            f"tests/test_big.py::test_{i}",
            "FAILED" if i % FAILED_EVERY == 0 else "PASSED",
            "f2p" if i < MANY_TESTS // 2 else "p2p",
        )
        for i in range(MANY_TESTS)
    )


class EpisodeSource(FakeSource):
    """The standard sample, plus fixed test lists per episode."""

    test_lists: dict[tuple[str, str], tuple[TestStatus, ...]]

    def episode_tests(self, run_id: str, episode_id: str, **kwargs: Any) -> tuple[TestStatus, ...]:
        if (run_id, episode_id) in self.test_lists:
            return self.test_lists[(run_id, episode_id)]
        return super().episode_tests(run_id, episode_id, **kwargs)


def source_with(
    detail: EpisodeDetail, *, trajectory_data: Trajectory | None = None, tests: Any = None
) -> FakeSource:
    """The standard sample with one more episode in the golden run."""
    base = make_source()
    key = (GOLDEN, detail.row.episode_id)
    src = EpisodeSource(
        task_rows=base.task_rows,
        episode_rows=(*base.episode_rows, detail.row),
        run_ids=base.run_ids,
        dataset_ids=base.dataset_ids,
        episode_details={key: detail},
        trajectories={key: trajectory_data} if trajectory_data is not None else {},
    )
    src.test_lists = {key: tests} if tests is not None else {}
    return src


def detail(episode_id: str, **overrides: Any) -> EpisodeDetail:
    """A full golden episode called `episode_id`. Row fields go in `row`, detail fields as keywords."""
    row_fields = overrides.pop("row", {})
    row = make_episode_row(episode_id=episode_id, **row_fields)
    return make_episode_detail(row, **overrides)


def lht_detail() -> EpisodeDetail:
    base = detail(
        "tablib-lht__oracle__0",
        row={"instance_id": LHT_TASK, "category": "lht", "reward": 0.97},
        reward_breakdown=breakdown(w_tests=0.8, w_rubric=0.2, w_similarity=0.0),
    )
    grade = replace(
        base.grade,
        milestones=(("pr-380", 1.0), ("pr-391", 0.5)),
        f2p=ClassCounts(total=8, passed=6, failed=tuple(f"tests/test_lht.py::test_{i}" for i in range(2))),
        status_counts=(Facet("PASSED", 318), Facet("FAILED", 2)),
    )
    return replace(base, grade=grade)


def crashed_detail() -> EpisodeDetail:
    return detail(
        "crashed__0",
        row={
            "policy": "cheater:ghost",
            "reward": 0.0,
            "resolved": False,
            "error": "docker: container exited 137",
        },
        grade=None,
        reward_breakdown=None,
        findings=(),
        rubric_score=None,
        rubric_items=(),
        rubric_skipped=(),
        patch=None,
        provenance=None,
        usage=(),
    )
