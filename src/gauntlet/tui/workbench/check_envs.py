"""Check env fingerprints: recompute each task's env fingerprint, the way `gauntlet check-envs` does."""

from __future__ import annotations

from textual.widget import Widget

from .. import actions
from ..jobtypes import JobRecord, JobSpec
from ..widgets.outcome import check_outcome
from .base import ActionForm, TaskSetsField, Values, register


@register
class CheckEnvs(ActionForm):
    action_id = "check_envs"
    fields = (
        TaskSetsField(
            name="tasks",
            label="Task sets",
            hint=(
                "A fingerprint hashes the install script and the dependency files at a task's base "
                "commit. It drifts when that script changes, so the env would rebuild differently."
            ),
        ),
    )

    def outcome(self, record: JobRecord) -> Widget | None:
        return check_outcome(record)

    def build(self, values: Values) -> JobSpec:
        return actions.check_envs(values.paths("tasks"))
