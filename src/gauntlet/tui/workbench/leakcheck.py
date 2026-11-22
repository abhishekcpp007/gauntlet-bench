"""Leak check: the 8 leak checks again on a task set, the way `gauntlet leakcheck` runs them."""

from __future__ import annotations

from .. import actions
from ..jobtypes import JobSpec
from .base import ActionForm, FieldError, TaskSetField, Values, register

CHECKS_HINT = (
    f"Each task gets all {actions.LEAK_CHECK_COUNT} checks. They look for the fix and the hidden tests "
    "anywhere an agent could read them, grader files, extra git history and an open network."
)


@register
class LeakCheck(ActionForm):
    action_id = "leakcheck"
    fields = (TaskSetField(name="tasks", label="Task set", hint=CHECKS_HINT),)

    def build(self, values: Values) -> JobSpec:
        tasks = values.path("tasks")
        if tasks is None:
            raise FieldError("Pick the task set.")
        return actions.leakcheck(tasks)
