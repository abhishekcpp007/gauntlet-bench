"""Try a patch: grade your own diff on one task, the way an agent's patch is graded. `o` opens
the episode it made: its run output names the episode, and `app.open_output` opens it."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import actions
from ..jobtypes import JobSpec
from .base import ActionForm, FieldError, PathField, TaskField, TaskSetField, Values, register

if TYPE_CHECKING:
    pass

PEEK_BYTES = 4096
MAKE_A_PATCH = "In a clone at the task's base commit, make your change and run git diff > my.diff."


def has_text(path: Path) -> bool:
    """Whether a file holds anything but whitespace. Reads at most one block."""
    with path.open("rb") as handle:
        return bool(handle.read(PEEK_BYTES).strip())


@dataclass(frozen=True, kw_only=True)
class PatchField(PathField):
    """A patch file that's there and has something in it."""

    def parse(self, raw: object) -> object:
        path = super().parse(raw)
        if isinstance(path, Path) and not has_text(path):
            raise FieldError(f"{path} is empty. {MAKE_A_PATCH}")
        return path


@register
class TryPatch(ActionForm):
    action_id = "try_patch"
    fields = (
        TaskSetField(name="tasks", label="Task set", hint="The set the task comes from."),
        TaskField(name="task", label="Task", hint="The one task to grade your patch on.", task_set="tasks"),
        PatchField(name="patch", label="Patch file", hint=MAKE_A_PATCH, placeholder="my.diff"),
    )

    def build(self, values: Values) -> JobSpec:
        tasks = values.path("tasks")
        task = values.text("task")
        patch = values.path("patch")
        if tasks is None or task is None or patch is None:
            raise FieldError("Pick the task set, the task and the patch file.")
        return actions.try_patch(values.workspace, tasks, task, patch)
