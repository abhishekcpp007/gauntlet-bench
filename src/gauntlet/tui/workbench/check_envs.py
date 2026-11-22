"""Check env fingerprints: recompute each task's env fingerprint, the way `gauntlet check-envs` does."""

from __future__ import annotations

from textual.widget import Widget

from .. import actions
from .. import format as fmt
from ..jobtypes import JobRecord, JobSpec
from ..models import DataSource
from ..widgets.outcome import check_outcome
from .base import ActionForm, Choice, MultiChoiceField, Values, register

NONE_PICKED: tuple[str, ...] = ()


def task_file_choices(source: DataSource) -> tuple[Choice, ...]:
    """Every task set that has a task file. The value is the file, so the builder gets it as is."""
    return tuple(
        Choice(d.tasks_file, f"{d.id} ({fmt.plural(d.tasks, 'task')})")
        for d in source.datasets()
        if d.tasks_file
    )


@register
class CheckEnvs(ActionForm):
    action_id = "check_envs"
    fields = (
        MultiChoiceField(
            name="tasks",
            label="Task sets",
            hint=(
                "A fingerprint hashes the install script and the dependency files at a task's base "
                "commit. It drifts when that script changes, so the env would rebuild differently."
            ),
            options=task_file_choices,
            default=NONE_PICKED,
        ),
    )

    def outcome(self, record: JobRecord) -> Widget | None:
        return check_outcome(record)

    def build(self, values: Values) -> JobSpec:
        return actions.check_envs(values.items("tasks"))
