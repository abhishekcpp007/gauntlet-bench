"""The Workbench's actions: one small module per action form. This docstring is the guide to adding one.

Add an action
    Write a module here, say `leakcheck.py`, with one `ActionForm` subclass, decorate it with
    `@register`, and import the module at the bottom of this file. That's all: the Workbench
    lists it under its group, draws its form, checks it, confirms it and runs it.

        @register
        class LeakCheck(ActionForm):
            action_id = "leakcheck"          # unique, also JobSpec.action
            title = "Leak check"             # the list entry and the form's title
            group = "check"                  # "make", "check" or "score"
            description = "Re-run the 8 leak checks on a task set."
            cost = "Docker for the env checks, about a minute per task."
            needs = ("docker",)              # "docker", "network", "api_key"
            fields = (TaskSetField(name="tasks", label="Task set", hint="The tasks to check."),)

            def build(self, values: Values) -> JobSpec:
                return actions.leakcheck(values.text("tasks"), values.workspace)

    `description` and `cost` are one plain line each: what it does, then what it costs (Docker,
    network, minutes, disk). Words follow the house rules: contractions, no em-dashes, never a
    list of exactly three things.

Declare fields
    Every field takes `name` (its key in `Values`), `label` (two or three words), `hint` (one line
    under it) and `required` (default True). The kinds, from `workbench.base`:
    `TextField` (`validate=` a function that returns an error sentence or None, `several=True`
    for a space separated list), `IntegerField` and `NumberField` (`minimum`, `maximum`),
    `DateField` (`YYYY-MM-DD`), `ChoiceField` and `MultiChoiceField` (fixed `choices`, or
    `options=` a function of the `DataSource` that runs in a thread; a multi-choice picks every
    option unless `default` says which), `SwitchField` (yes or no), `PathField` (`kind="file"` or
    `"folder"`, `must_exist=False` for an output that may be new; `ctrl+o` browses),
    `TaskSetField`, `TaskField` (`task_set=` the name of the task set field it lists from) and
    `RunField`. Give each a `default` where one makes sense. `repo_name` is a ready validator.

Validate
    A field checks itself when the user leaves it and again on review: an empty required field,
    a number out of range, a bad date, a path that isn't there. Put rules about one value in its
    `validate`. Rules that need several values go in `build`: raise `BuildError` (or the
    builders' own error, any `ValueError` will do) and the form shows its message on top.

Build a spec
    `build(values)` returns a `JobSpec`. Read values with `values.text`, `items`, `integer`,
    `number`, `flag` and `path`; each gives None (or `()`) for an empty optional field.
    `values.workspace` is where jobs write: outputs go under its `tasks/` or `runs/`. Call the
    builder in `gauntlet.tui.actions` for your action rather than writing argument lists here, so
    the command a reviewer sees is the one the builders test. Override `after(job, app)` when
    "open what it made" means more than opening the first output (Try a patch opens its episode
    with `app.open_episode`); return False when there's nothing to open.

Test it
    Use `tests/tui/workfakes.py`. Mount the form alone with `form_app(MyForm())`, set fields
    with `fill(view, name=value, ...)`, call `view.review()` and assert on the `JobSpec` it
    returns, or on `row_errors(view)` and the banner when it refuses. Then open it in the
    Workbench with `GauntletApp(make_source(), jobs=ScriptedRunner())` and check the confirm
    step shows your command lines. `ScriptedRunner` records what was submitted and plays back
    the events you script (`start`, `line`, `step`, `finish`), and `make_machine()` builds a
    `Machine`, say with Docker down. See `tests/tui/test_form_examples.py`.

Don't
    Import harness modules in a form (only the builders), start or watch processes (the runner
    does that), read the environment for keys or tokens (the machine check does that, and never
    shows a value), name colours or symbols (the theme does that), or put markup in labels and
    hints (they're shown literally).
"""

from __future__ import annotations

from collections.abc import Sequence

from .base import ActionForm, registered


def catalogue() -> Sequence[type[ActionForm]]:
    """Every action the Workbench offers, grouped."""
    return registered()


from . import calibrate, scan  # noqa: E402  (importing a form registers it)

__all__ = ["calibrate", "catalogue", "scan"]
