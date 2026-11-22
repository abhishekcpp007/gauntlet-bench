"""From fresh PRs: collect a repo's merged PRs, then build a leak-checked task from each one that
makes the cut. When the job ends, its Result pane says what was kept and why the rest wasn't."""

from __future__ import annotations

from collections.abc import Sequence

from textual.widget import Widget

from .. import actions
from ..jobtypes import FINISHED, JobRecord, JobSpec, Output
from ..widgets.buildresult import BuildResult, built_outputs
from ..widgets.form import FormView
from ..widgets.formextras import FormNote
from .base import (
    ActionForm,
    Choice,
    ChoiceField,
    DateField,
    FieldError,
    IntegerField,
    SwitchField,
    TextField,
    Values,
    register,
    repo_name,
)

LIVE_PRS = 186
LIVE_TASKS = 53
"""The shipped Live set's funnel, from datasets/gauntlet-live-2026-11/stats.json (a test checks it)."""

SUITE_RUNS = actions.SUITE_RUNS

SCOPES = (
    Choice("full", "full: the whole test suite", "catches a break anywhere in the repo"),
    Choice("changed", "changed: only the PR's test files", "faster, but blind to breaks elsewhere"),
)
RARELY_KEPT = (
    f"Most PRs don't make a task, and that's normal: the shipped Live set kept {LIVE_TASKS} tasks "
    f"from {LIVE_PRS} PRs."
)
COSTS = (
    "Needs Docker and the network. Each PR takes minutes, since its tests run "
    f"{SUITE_RUNS} times at the default fix runs. {RARELY_KEPT}"
)


@register
class MakeTasks(ActionForm):
    action_id = "make_tasks"
    fields = (
        TextField(
            name="repos",
            label="Repos",
            hint="One or more GitHub repos, written owner/name, with spaces between.",
            placeholder="pallets/click",
            validate=repo_name,
            several=True,
        ),
        DateField(
            name="merged_after",
            label="Merged after",
            hint="Optional. Only PRs merged after this day, written 2026-11-05. Empty takes the newest.",
            required=False,
        ),
        IntegerField(
            name="limit",
            label="PR limit",
            hint="How many merged PRs to look at in each repo, newest first.",
            default=actions.COLLECT_LIMIT,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_LIMIT,
        ),
        ChoiceField(
            name="scope",
            label="Test scope",
            hint="Which tests grade the task. Full runs the whole suite, changed only the PR's test files.",
            choices=SCOPES,
            default=actions.SCOPE,
        ),
        IntegerField(
            name="fix_runs",
            label="Fix runs",
            hint=(
                "How often the merged fix is run, to catch flaky tests. "
                f"At {actions.FIX_RUNS} the tests run {SUITE_RUNS} times a PR."
            ),
            default=actions.FIX_RUNS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_FIX_RUNS,
        ),
        TextField(
            name="python",
            label="Python",
            hint="The Python version the task's environment is built with.",
            default=actions.PYTHON,
        ),
        SwitchField(
            name="git_fallback",
            label="Git fallback",
            hint="If GitHub's API rate-limits you, read the merged PRs from the repo's git history.",
        ),
        TextField(
            name="name",
            label="Task set name",
            hint="Optional. Empty lets the workspace pick one from the repo and the time.",
            required=False,
        ),
    )

    def outcome(self, record: JobRecord) -> Widget | None:
        return BuildResult(record, note=RARELY_KEPT) if record.state in FINISHED else None

    def openable(self, record: JobRecord) -> tuple[Output, ...]:
        return built_outputs(record)

    def extras(self, view: FormView) -> Sequence[tuple[Widget, str | None]]:
        return ((FormNote(COSTS, id="make-tasks-costs"), None),)

    def build(self, values: Values) -> JobSpec:
        limit = values.integer("limit")
        fix_runs = values.integer("fix_runs")
        scope = values.text("scope")
        python = values.text("python")
        if limit is None or fix_runs is None or scope is None or python is None:
            raise FieldError("Fill in the PR limit, the scope, the fix runs and the Python version.")
        return actions.make_tasks(
            values.workspace,
            values.items("repos"),
            merged_after=values.text("merged_after"),
            limit=limit,
            scope=scope,
            fix_runs=fix_runs,
            python=python,
            git_fallback=values.flag("git_fallback"),
            name=values.text("name"),
        )
