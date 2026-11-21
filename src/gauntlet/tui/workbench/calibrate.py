"""Calibrate: the real fix, a blank answer and the 9 cheats on a task set, checked the way
`gauntlet calibrate` checks them.
"""

from __future__ import annotations

import time
from pathlib import Path

from ..jobtypes import JobSpec, Output, Step
from ..models import DataSource
from .base import (
    ActionForm,
    Choice,
    IntegerField,
    MultiChoiceField,
    TaskSetField,
    TextField,
    Values,
    register,
)

DEFAULT_SAMPLE = 3
MAX_SAMPLE = 500
DEFAULT_WORKERS = 2
MAX_WORKERS = 8
SHIPPED_PREFIX = "gauntlet-"
STAMP = "%Y%m%d-%H%M%S"


def policy_choices(source: DataSource) -> tuple[Choice, ...]:
    return tuple(Choice(p.id, p.id, p.what) for p in source.reference().policies)


# Stand-in until the builders merge: swap these two for the builder in gauntlet.tui.actions.
def tasks_file(task_set: str, workspace: Path) -> Path:
    made = workspace / "tasks" / task_set / "tasks.jsonl"
    folder = task_set if task_set.startswith(SHIPPED_PREFIX) else f"{SHIPPED_PREFIX}{task_set}"
    return made if made.is_file() else Path("datasets") / folder / "tasks.jsonl"


def calibrate_spec(
    task_set: str,
    workspace: Path,
    *,
    sample: int | None,
    seed: str | None,
    policies: tuple[str, ...],
    workers: int,
) -> JobSpec:
    name = f"calibrate-{task_set}-{time.strftime(STAMP)}"
    out = workspace / "runs" / name
    argv = ["calibrate", "--tasks", str(tasks_file(task_set, workspace))]
    if sample:
        argv += ["--sample", str(sample)]
    if seed:
        argv += ["--seed", seed]
    if policies:
        argv += ["--policies", ",".join(policies)]
    argv += ["--workers", str(workers), "-o", str(out)]
    return JobSpec(
        action=Calibrate.action_id,
        title=f"Calibrate {task_set}",
        steps=(Step("calibrate", tuple(argv)),),
        needs=("docker",),
        outputs=(Output("run", str(out), f"run {name}"),),
    )


@register
class Calibrate(ActionForm):
    action_id = "calibrate"
    title = "Calibrate"
    group = "check"
    description = "Red-team the grader on a task set: the real fix must win and every cheat must lose."
    cost = "Docker, a few minutes per task and policy, and a few GB of disk while it runs."
    needs = ("docker",)
    fields = (
        TaskSetField(name="tasks", label="Task set", hint="The tasks to calibrate on."),
        IntegerField(
            name="sample",
            label="Sample size",
            hint=f"Random tasks to use, up to {MAX_SAMPLE}. 0 uses every task.",
            default=DEFAULT_SAMPLE,
            minimum=0,
            maximum=MAX_SAMPLE,
        ),
        TextField(
            name="seed",
            label="Seed",
            hint="Optional. The same seed picks the same sample. Empty uses today's date.",
            required=False,
        ),
        MultiChoiceField(
            name="policies",
            label="Policies",
            hint="Every policy by default: the oracle, the no-op and each cheat.",
            options=policy_choices,
        ),
        IntegerField(
            name="workers",
            label="Workers",
            hint=f"Tasks run side by side, each in its own container. 1 to {MAX_WORKERS}.",
            default=DEFAULT_WORKERS,
            minimum=1,
            maximum=MAX_WORKERS,
        ),
    )

    def build(self, values: Values) -> JobSpec:
        task_set = values.text("tasks")
        workers = values.integer("workers")
        assert task_set is not None and workers is not None
        return calibrate_spec(
            task_set,
            values.workspace,
            sample=values.integer("sample"),
            seed=values.text("seed"),
            policies=values.items("policies"),
            workers=workers,
        )
