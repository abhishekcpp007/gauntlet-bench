"""Calibrate: the real fix, a blank answer and every cheat on a task set, checked the way
`gauntlet calibrate` checks them."""

from __future__ import annotations

from textual.widget import Widget

from .. import actions
from ..jobtypes import JobRecord, JobSpec
from ..models import DataSource
from ..widgets.outcome import check_outcome
from .base import (
    ActionForm,
    Choice,
    FieldError,
    IntegerField,
    MultiChoiceField,
    TaskSetField,
    TextField,
    Values,
    register,
)

FIRST_LOOK = 3


def policy_choices(source: DataSource) -> tuple[Choice, ...]:
    """The policies `gauntlet calibrate` runs, described from the reference."""
    described = {p.id: p.what for p in source.reference().policies}
    return tuple(Choice(p, p, described.get(p, "")) for p in actions.CALIBRATION_POLICIES)


@register
class Calibrate(ActionForm):
    action_id = "calibrate"
    fields = (
        TaskSetField(name="tasks", label="Task set", hint="The tasks to calibrate on."),
        IntegerField(
            name="sample",
            label="Sample size",
            hint=f"Random tasks to use. {actions.SAMPLE_ALL} uses every task, which can take hours.",
            default=FIRST_LOOK,
            minimum=actions.SAMPLE_ALL,
            maximum=actions.MAX_SAMPLE,
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
            hint="Every policy by default, the oracle and the no-op included.",
            options=policy_choices,
        ),
        IntegerField(
            name="workers",
            label="Workers",
            hint=f"Tasks run side by side, each in its own container. Up to {actions.MAX_WORKERS}.",
            default=actions.WORKERS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_WORKERS,
        ),
    )

    def outcome(self, record: JobRecord) -> Widget | None:
        return check_outcome(record)

    def build(self, values: Values) -> JobSpec:
        tasks = values.path("tasks")
        sample = values.integer("sample")
        workers = values.integer("workers")
        if tasks is None or sample is None or workers is None:
            raise FieldError("Fill in the task set, the sample size and the workers.")
        return actions.calibrate(
            values.workspace,
            tasks,
            sample=sample,
            seed=values.text("seed"),
            policies=values.items("policies"),
            workers=workers,
        )
