"""The Workbench's action forms: one small module per form. This docstring is the guide to adding one.

The actions themselves are the engine's: `gauntlet.tui.actions.ACTIONS` lists all nine, with
their titles, groups, descriptions and needs, and the Workbench lists every one of them. An
action with no form yet is listed as "not available yet". A form makes it usable.

Add a form
    Write one new module here, say `leakcheck.py`, holding one `ActionForm` subclass decorated
    with `@register`. That's the only file you touch: `forms()` below imports every module in
    this package, so nothing has to list yours, and two people adding forms at once never edit
    the same file. Put its tests in their own `tests/tui/test_form_<action>.py`.

        from .. import actions
        from .base import ActionForm, TaskSetField, Values, register

        @register
        class LeakCheck(ActionForm):
            action_id = "leakcheck"          # an id from actions.ACTIONS
            fields = (TaskSetField(name="tasks", label="Task set", hint="The tasks to check."),)

            def build(self, values: Values) -> JobSpec:
                return actions.leakcheck(values.path("tasks"))

    Don't repeat the title, group, description or needs: they come from the action's
    `ActionInfo`. Labels and hints follow the house rules: contractions, no em-dashes, never a
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
    `TaskSetField` (gives the set's `tasks.jsonl`), `TaskSetsField` (any number of sets, read
    with `values.paths`), `TaskField` (`task_set=` the name of the task set field it lists from)
    and `RunField` (`results=True` gives its results file). Give fields that belong together the
    same `group`, like "Limits", and they sit under one heading. Take defaults and limits from
    the constants in `gauntlet.tui.actions`, never your own copies.

Validate
    A field checks itself when the user leaves it and again on review: an empty required field,
    a number out of range, a bad date, a path that isn't there. The builder checks the rest and
    raises `actions.ActionError`; the form shows its message on top. Don't repeat a check the
    builder already makes.

Build a spec
    `build(values)` calls the action's builder in `gauntlet.tui.actions` and returns its
    `JobSpec`. Never write argument lists in a form. Read values with `values.text`, `items`,
    `integer`, `number`, `flag` and `path`; each gives None (or `()`) for an empty optional
    field. A task set or run field gives its id with `text` and its file with `path`.
    `values.workspace` is the `Workspace` the builders take.

Hooks, all optional
    `extras(view)` adds widgets of the form's own to its view, each after a named field or above
    them all: a `FormNote` with something the description doesn't say, or a button like Make
    from a release range's List ranges. `outcome(record)` returns a widget for the Job screen's
    Result pane once the job has finished: `OutcomeView` for a scan or a check, `BuildResult` for
    a build, `ReportOutcome` for a report. It reads what it needs in a thread. `openable(record)`
    leaves out outputs not worth opening, like an empty task set, and `opens(record)` says whether
    `o` does anything. `after(job, app)` is what `o` opens; the default opens the first openable
    output, and a run output that names an episode opens that episode.

Test it
    Use `tests/tui/fakejobs.py` and `tests/tui/wait.py` (`settle` and `wait_until`: wait for a
    condition, never for a fixed time). Mount the form alone with `form_app(MyForm(), workspace=...)`,
    set fields with `fill(view, name=value, ...)`, call `view.review()` and assert on the
    `JobSpec` it returns, or on `row_errors(view)` and the banner when it refuses. Then open it
    in the Workbench with `GauntletApp(make_source(), jobs=FakeJobRunner())` and check the
    confirm step shows the command lines. `FakeJobRunner.script(action, lines, exit_code=...)`
    says what its jobs print and how they end. See `tests/tui/test_form_examples.py`.

Don't
    Import harness modules in a form (only `gauntlet.tui.actions`), start or watch processes (the
    runner does that), read the environment for keys or tokens (the machine check does that,
    and never shows a value), name colours or symbols (the theme does that), or put markup in
    labels and hints (they're shown literally).
"""

from __future__ import annotations

import importlib
import pkgutil

from .base import ActionForm, registered

SKIPPED = frozenset({"base"})


def forms() -> dict[str, type[ActionForm]]:
    """Every form in this package, by action id. Importing a form's module registers it."""
    for module in pkgutil.iter_modules(__path__):
        if module.name not in SKIPPED:
            importlib.import_module(f"{__name__}.{module.name}")
    return registered()
