"""The plain half of the form framework: fields, the values they give, `ActionForm` and the registry.

Nothing here imports Textual. A field says what it accepts and turns what the user typed into a
value, or raises `FieldError` with one plain sentence. `widgets.form` draws the fields and calls
`check` when the user leaves one and again before review.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from ..actions import ACTIONS
from ..jobtypes import ActionGroup, ActionInfo, JobRecord, JobSpec, Machine, Need
from ..models import DataSource
from ..workspace import Workspace

if TYPE_CHECKING:
    from textual.widget import Widget

    from ..app import GauntletApp
    from ..widgets.form import FormView

PathKind = Literal["file", "folder"]

GROUPS: tuple[tuple[ActionGroup, str], ...] = (("make", "Make tasks"), ("check", "Check"), ("score", "Score"))
NEED_LABELS: dict[Need, str] = {"docker": "Docker", "network": "network", "api_key": "an Anthropic key"}
SEPARATORS = re.compile(r"[\s,]+")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class FieldError(ValueError):
    """What's wrong with one field's value, as one plain sentence."""


@dataclass(frozen=True, slots=True)
class Choice:
    """One option in a choice, a multi-choice or a picker: the value, what it's called, a note,
    and for a task set or a run the file a job reads (`tasks.jsonl`, `results.jsonl`)."""

    value: str
    label: str
    detail: str = ""
    path: str | None = None


ChoiceSource = Callable[[DataSource], Sequence[Choice]]


@dataclass(frozen=True, kw_only=True)
class Field:
    """One input on a form. `name` is the key in `Values`; `label` and `hint` are what the user reads.

    An empty value is None, which is fine unless `required` is set. Subclasses override `parse`
    for a value that isn't empty.
    """

    name: str
    label: str
    hint: str = ""
    required: bool = True

    def check(self, raw: object) -> object:
        """`raw` (what the widget holds) as a value, or `FieldError` saying what's wrong."""
        if raw is None or raw == "" or raw == ():
            if self.required:
                raise FieldError(f"{self.label} is needed.")
            return None
        return self.parse(raw)

    def parse(self, raw: object) -> object:
        return raw


@dataclass(frozen=True, kw_only=True)
class TextField(Field):
    """Free text. `validate` returns an error sentence or None. With `several`, the text is split on
    spaces and commas and the value is a tuple, each item validated on its own."""

    default: str = ""
    placeholder: str = ""
    validate: Callable[[str], str | None] | None = None
    several: bool = False

    def check(self, raw: object) -> object:
        return super().check(str(raw or "").strip())

    def parse(self, raw: object) -> object:
        text = str(raw)
        items = tuple(item for item in SEPARATORS.split(text) if item) if self.several else (text,)
        for item in items:
            if self.validate is not None and (problem := self.validate(item)) is not None:
                raise FieldError(problem)
        return items if self.several else text


@dataclass(frozen=True, kw_only=True)
class IntegerField(Field):
    """A whole number from `minimum` to `maximum` (either end may be open)."""

    default: int | None = None
    minimum: int | None = None
    maximum: int | None = None

    def check(self, raw: object) -> object:
        return super().check(str(raw or "").strip())

    def parse(self, raw: object) -> object:
        try:
            value = int(str(raw))
        except ValueError:
            raise FieldError(f"{self.label} must be a whole number.") from None
        return in_range(value, self.minimum, self.maximum, self.label)


@dataclass(frozen=True, kw_only=True)
class NumberField(Field):
    """Any number from `minimum` to `maximum`."""

    default: float | None = None
    minimum: float | None = None
    maximum: float | None = None

    def check(self, raw: object) -> object:
        return super().check(str(raw or "").strip())

    def parse(self, raw: object) -> object:
        try:
            value = float(str(raw))
        except ValueError:
            raise FieldError(f"{self.label} must be a number.") from None
        return in_range(value, self.minimum, self.maximum, self.label)


@dataclass(frozen=True, kw_only=True)
class DateField(Field):
    """A date written `YYYY-MM-DD`. The value stays a string, the way the CLI takes it."""

    default: str = ""

    def check(self, raw: object) -> object:
        return super().check(str(raw or "").strip())

    def parse(self, raw: object) -> object:
        text = str(raw)
        if ISO_DATE.fullmatch(text) is None:
            raise FieldError(f"{self.label} must look like 2026-11-05.")
        try:
            date.fromisoformat(text)
        except ValueError:
            raise FieldError(f"{text} isn't a real date.") from None
        return text


@dataclass(frozen=True, kw_only=True)
class ChoiceField(Field):
    """One of a fixed list (`choices`), or of a list read from the data (`options`)."""

    choices: tuple[Choice, ...] = ()
    options: ChoiceSource | None = None
    default: str | None = None


@dataclass(frozen=True, kw_only=True)
class SwitchField(Field):
    """Yes or no. Never empty, so `required` doesn't apply."""

    default: bool = False
    required: bool = False

    def check(self, raw: object) -> object:
        return bool(raw)


@dataclass(frozen=True, kw_only=True)
class MultiChoiceField(Field):
    """Any number of a list, like policies. `default` None picks every option; the value is a tuple."""

    choices: tuple[Choice, ...] = ()
    options: ChoiceSource | None = None
    default: tuple[str, ...] | None = None

    def check(self, raw: object) -> object:
        if isinstance(raw, Sequence) and not isinstance(raw, str):
            raw = tuple(str(item) for item in raw)
        if raw == () and self.required:
            raise FieldError(f"Pick at least one of {self.label.lower()}.")
        return raw or None


@dataclass(frozen=True, kw_only=True)
class PathField(Field):
    """A file or folder. With `must_exist` it has to be there already; otherwise it may be new, but
    it can't be the wrong kind of thing. `browse` offers a file browser."""

    kind: PathKind = "file"
    must_exist: bool = True
    default: str = ""
    placeholder: str = ""

    def check(self, raw: object) -> object:
        return super().check(str(raw or "").strip())

    def parse(self, raw: object) -> object:
        path = Path(str(raw)).expanduser()
        wrong = path.is_dir() if self.kind == "file" else path.exists() and not path.is_dir()
        if wrong:
            raise FieldError(f"{path} is a {'folder' if self.kind == 'file' else 'file'}, not a {self.kind}.")
        if self.must_exist and not path.exists():
            raise FieldError(f"There's no {self.kind} at {path}.")
        return path


@dataclass(frozen=True, kw_only=True)
class TaskSetField(Field):
    """A task set: a shipped one, or one a job made in the workspace. The value is its `Choice`:
    `values.text` gives its id and `values.path` its `tasks.jsonl`."""

    def parse(self, raw: object) -> object:
        return picked_file(raw, f"{self.label} has no task file to read.")


@dataclass(frozen=True, kw_only=True)
class TaskField(Field):
    """One task, searchable. With `task_set`, the picker only lists tasks from the set chosen in
    the field of that name. The value is the instance id."""

    task_set: str | None = None

    def parse(self, raw: object) -> object:
        return raw.value if isinstance(raw, Choice) else raw


@dataclass(frozen=True, kw_only=True)
class RunField(Field):
    """A loaded run. The value is its `Choice`: `values.text` gives its id and `values.path` its
    results file. With `results`, a run whose results file wasn't shipped can't be picked."""

    results: bool = False

    def parse(self, raw: object) -> object:
        if self.results:
            return picked_file(raw, "That run only has summary rows, so there's no results file to read.")
        return raw


PREFILL_KINDS: dict[str, type[Field]] = {
    "task_set": TaskSetField,
    "task": TaskField,
    "run": RunField,
    "patch": PathField,
}
SHORTCUT_KEYS: dict[str, str] = {
    "make_tasks": "M",
    "leakcheck": "L",
    "check_envs": "E",
    "calibrate": "C",
    "run_policies": "O",
    "try_patch": "P",
    "report": "R",
}


def shortcut(action_id: str) -> tuple[str, str]:
    """The key and the binding action for a viewer screen's way into the Workbench on `action_id`:
    `Binding(*shortcut("calibrate"), "Calibrate")`."""
    return SHORTCUT_KEYS[action_id], f"app.workbench('{action_id}')"


STILL_LOADING = "Still loading. Try again in a moment."
SUMMARY_ONLY_RUN = "This run only has summary rows, so there's no results file to report on."


def fits_prefill(key: str, field: Field) -> bool:
    """Whether `field` is the kind a prefill `key` names. A patch only goes in a file path."""
    kind = PREFILL_KINDS.get(key)
    if kind is None or not isinstance(field, kind):
        return False
    return not isinstance(field, PathField) or field.kind == "file"


def place_prefill(fields: Sequence[Field], prefill: Mapping[str, str]) -> dict[str, tuple[Field, str]]:
    """Where each prefill value goes, by meaning, not by field name: `task_set` in the first task
    set field, `task` in the first task field, `run` in the first run field and `patch` in the
    first file path. A key with no field of its kind is left out."""
    placed: dict[str, tuple[Field, str]] = {}
    for key, value in prefill.items():
        field = next((f for f in fields if fits_prefill(key, f)), None)
        if field is not None:
            placed[key] = (field, value)
    return placed


def picked_file(raw: object, missing: str) -> Choice:
    if not isinstance(raw, Choice) or raw.path is None:
        raise FieldError(missing)
    return raw


def in_range(value: float, minimum: float | None, maximum: float | None, label: str) -> float:
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        if minimum is not None and maximum is not None:
            raise FieldError(f"{label} must be from {minimum} to {maximum}.")
        if minimum is not None:
            raise FieldError(f"{label} must be {minimum} or more.")
        raise FieldError(f"{label} must be {maximum} or less.")
    return value


def repo_name(value: str) -> str | None:
    """A validator for `TextField`: a GitHub repo written `owner/name`."""
    return None if REPO.fullmatch(value) else f"{value} isn't a repo. Write it as owner/name."


@dataclass(frozen=True, slots=True)
class Values:
    """The checked values of a form, by field name, and the workspace jobs write into."""

    workspace: Workspace
    data: Mapping[str, object]

    def __getitem__(self, name: str) -> object:
        return self.data[name]

    def text(self, name: str) -> str | None:
        value = self.data.get(name)
        if isinstance(value, Choice):
            return value.value
        return None if value is None else str(value)

    def items(self, name: str) -> tuple[str, ...]:
        value = self.data.get(name)
        if value is None:
            return ()
        return tuple(str(v) for v in value) if isinstance(value, tuple) else (str(value),)

    def integer(self, name: str) -> int | None:
        value = self.data.get(name)
        return None if value is None else int(str(value))

    def number(self, name: str) -> float | None:
        value = self.data.get(name)
        return None if value is None else float(str(value))

    def flag(self, name: str) -> bool:
        return bool(self.data.get(name))

    def path(self, name: str) -> Path | None:
        value = self.data.get(name)
        if isinstance(value, Choice):
            return None if value.path is None else Path(value.path)
        return None if value is None else Path(str(value))


@dataclass(frozen=True, slots=True)
class NeedCheck:
    """One thing a job needs and whether the machine has it. `met` is None when it can't be told."""

    need: Need
    label: str
    met: bool | None
    detail: str


def check_needs(needs: Sequence[Need], machine: Machine) -> tuple[NeedCheck, ...]:
    out: list[NeedCheck] = []
    for need in needs:
        label = NEED_LABELS[need]
        if need == "docker":
            detail = "running" if machine.docker_running else f"not running: {machine.docker_detail}"
            out.append(NeedCheck(need, label, machine.docker_running, detail))
        elif need == "api_key":
            detail = (
                "ANTHROPIC_API_KEY is set" if machine.anthropic_key_set else "ANTHROPIC_API_KEY isn't set"
            )
            out.append(NeedCheck(need, label, machine.anthropic_key_set, detail))
        else:
            out.append(NeedCheck(need, label, None, "not checked"))
    return tuple(out)


def blocked_reason(needs: Sequence[Need], machine: Machine) -> str | None:
    """Why a job with these needs can't start on this machine, or None when it can."""
    for check in check_needs(needs, machine):
        if check.met is False:
            if check.need == "docker":
                return (
                    f"Docker isn't running ({machine.docker_detail}). Start it, then press r to check again."
                )
            return "ANTHROPIC_API_KEY isn't set. Set it in the shell you start gauntlet from."
    return None


class ActionForm:
    """The form for one of the engine's actions. Subclass it in its own module in this package,
    set `action_id` to an id from `actions.ACTIONS`, declare `fields` and `build`, and decorate
    it with `@register`. The title, group, description and needs come from that `ActionInfo`, so
    the list and the engine can't drift. See the guide in `gauntlet.tui.workbench`.

    `after` opens what a succeeded job made; the default opens its first output.
    """

    action_id: ClassVar[str]
    fields: ClassVar[tuple[Field, ...]] = ()

    def build(self, values: Values) -> JobSpec:
        """The job these values make, from the builder in `gauntlet.tui.actions`. An
        `ActionError` (any `ValueError`) refuses with its message."""
        raise NotImplementedError

    def extras(self, view: FormView) -> Sequence[tuple[Widget, str | None]]:
        """Widgets of the form's own to add to its view, each with the name of the field it goes
        after, or None to go above the fields. The default adds none."""
        return ()

    def outcome(self, record: JobRecord) -> Widget | None:
        """A widget for the Job screen's Result pane once `record` has finished: what the job found
        or made, read in a thread. None, the default, leaves the pane out."""
        return None

    def after(self, job: JobRecord, app: GauntletApp) -> bool:
        """Open what `job` made. Returns False when there's nothing to open."""
        for output in job.spec.outputs:
            app.open_output(output)
            return True
        return False


def action_info(action_id: str) -> ActionInfo | None:
    """The engine's record for an action id, or None for an id it doesn't know."""
    return next((info for info in ACTIONS if info.id == action_id), None)


_REGISTRY: dict[str, type[ActionForm]] = {}


def register(form: type[ActionForm]) -> type[ActionForm]:
    """Give one of the engine's actions its form. Use it as a class decorator."""
    if action_info(form.action_id) is None:
        raise ValueError(f"{form.action_id} isn't one of the actions in gauntlet.tui.actions.ACTIONS")
    if _REGISTRY.get(form.action_id, form) is not form:
        raise ValueError(f"two forms are registered for {form.action_id}")
    _REGISTRY[form.action_id] = form
    return form


def registered() -> dict[str, type[ActionForm]]:
    """Every registered form, by action id."""
    return dict(_REGISTRY)
