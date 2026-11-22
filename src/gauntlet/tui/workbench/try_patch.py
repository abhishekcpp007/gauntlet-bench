"""Try a patch: grade your own diff on one task, the way an agent's patch is graded, then open
the episode it made."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .. import actions
from ..jobtypes import JobRecord, JobSpec
from ..store import WORKSPACE_PREFIX
from .base import ActionForm, FieldError, PathField, TaskField, TaskSetField, Values, register

if TYPE_CHECKING:
    from ..app import GauntletApp

MAKE_A_PATCH = "In a clone at the task's base commit, make your change and run git diff > my.diff."


@dataclass(frozen=True, kw_only=True)
class PatchField(PathField):
    """A patch file that's there and has something in it."""

    def parse(self, raw: object) -> object:
        path = super().parse(raw)
        if isinstance(path, Path) and not path.read_bytes().strip():
            raise FieldError(f"{path} is empty. {MAKE_A_PATCH}")
        return path


def run_id_for(app: GauntletApp, folder: Path) -> str:
    """The loaded run at `folder`, found by path, or the id the store gives a workspace run."""
    wanted = folder.resolve()
    for run in app.source.runs():
        if run.path is not None and Path(run.path).resolve() == wanted:
            return run.id
    return f"{WORKSPACE_PREFIX}{folder.name}"


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

    def after(self, job: JobRecord, app: GauntletApp) -> bool:
        for output in job.spec.outputs:
            if output.kind == "run" and output.episode_id is not None:
                app.open_episode(run_id_for(app, Path(output.path)), output.episode_id)
                return True
        return super().after(job, app)
