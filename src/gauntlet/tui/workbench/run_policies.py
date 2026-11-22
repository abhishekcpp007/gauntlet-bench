"""Run policies: grade scripted policies, a model or your own patch on a task set with `gauntlet run`."""

from __future__ import annotations

from .. import actions
from ..jobtypes import JobSpec
from .base import (
    ActionForm,
    Choice,
    ChoiceField,
    FieldError,
    IntegerField,
    MultiChoiceField,
    NumberField,
    TaskSetField,
    TextField,
    Values,
    register,
)
from .calibrate import policy_choices

LIMITS = "Limits"
CATEGORY_NAMES = {"swe": "swe, single-PR tasks", "lht": "lht, long release-range tasks"}


@register
class RunPolicies(ActionForm):
    action_id = "run_policies"
    fields = (
        TaskSetField(name="tasks", label="Task set", hint="The tasks to grade every policy on."),
        MultiChoiceField(
            name="policies",
            label="Scripted policies",
            hint="Starts on gauntlet run's own default. Each one plays every task.",
            options=policy_choices,
            default=actions.RUN_POLICIES,
            required=False,
        ),
        TextField(
            name="extra",
            label="More policies",
            hint="Optional. claude:<model> plays a model and patch:<file> grades a diff.",
            placeholder="claude:claude-opus-5-5",
            required=False,
            several=True,
        ),
        IntegerField(
            name="attempts",
            label="Attempts",
            hint="Episodes per task for each policy. More than one gives pass@k.",
            default=actions.ATTEMPTS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_ATTEMPTS,
        ),
        IntegerField(
            name="workers",
            label="Workers",
            hint=f"Episodes run side by side, each in its own container. Up to {actions.MAX_WORKERS}.",
            default=actions.WORKERS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_WORKERS,
        ),
        ChoiceField(
            name="category",
            label="Category",
            hint="Optional. Only run tasks of this kind. Empty runs them all.",
            choices=tuple(Choice(c, CATEGORY_NAMES.get(c, c)) for c in actions.CATEGORIES),
            required=False,
        ),
        IntegerField(
            name="max_steps",
            label="Max steps",
            hint="Optional. Commands an agent may run in one episode. Empty uses each category's own cap.",
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_STEPS,
            required=False,
        ),
        IntegerField(
            name="max_episodes",
            label="Episodes",
            hint="Optional. Episodes the whole run may play. The run stops at the first limit it hits.",
            group=LIMITS,
            minimum=actions.AT_LEAST_ONE,
            required=False,
        ),
        IntegerField(
            name="max_tokens",
            label="Tokens",
            hint="Optional. Model tokens the whole run may use.",
            group=LIMITS,
            minimum=actions.AT_LEAST_ONE,
            required=False,
        ),
        NumberField(
            name="max_seconds",
            label="Seconds",
            hint="Optional. How long the whole run may take.",
            group=LIMITS,
            required=False,
        ),
        NumberField(
            name="max_usd",
            label="Dollars",
            hint="Optional. What the run may cost. It needs prices below.",
            group=LIMITS,
            required=False,
        ),
        TextField(
            name="prices",
            label="Prices",
            hint="Optional. Dollars per million tokens in and out, by policy prefix.",
            placeholder="claude:=3/15",
            required=False,
            group=LIMITS,
        ),
    )

    def build(self, values: Values) -> JobSpec:
        tasks = values.path("tasks")
        attempts = values.integer("attempts")
        workers = values.integer("workers")
        if tasks is None or attempts is None or workers is None:
            raise FieldError("Fill in the task set, the attempts and the workers.")
        return actions.run_policies(
            values.workspace,
            tasks,
            (*values.items("policies"), *values.items("extra")),
            attempts=attempts,
            workers=workers,
            category=values.text("category"),
            max_steps=values.integer("max_steps"),
            max_episodes=values.integer("max_episodes"),
            max_tokens=values.integer("max_tokens"),
            max_seconds=values.number("max_seconds"),
            max_usd=values.number("max_usd"),
            prices=values.text("prices"),
        )
