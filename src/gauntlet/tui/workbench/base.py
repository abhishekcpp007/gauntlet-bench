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

from ..jobtypes import ActionGroup, JobRecord, JobSpec, Machine, Need
from ..models import DataSource

if TYPE_CHECKING:
    from ..app import GauntletApp

PathKind = Literal["file", "folder"]

GROUPS: tuple[tuple[ActionGroup, str], ...] = (("make", "Make tasks"), ("check", "Check"), ("score", "Score"))
NEED_LABELS: dict[Need, str] = {"docker": "Docker", "network": "network", "api_key": "an Anthropic key"}
SEPARATORS = re.compile(r"[\s,]+")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class FieldError(ValueError):
    """What's wrong with one field's value, as one plain sentence."""


class BuildError(ValueError):
    """The values are each fine but don't make a job together. The form shows the message on top."""


@dataclass(frozen=True, slots=True)
class Choice:
    """One option in a choice, a multi-choice or a picker: the value, what it's called, a note."""

    value: str
    label: str
    detail: str = ""


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
    """A task set: a shipped one, or one a job made in the workspace. The value is its id."""


@dataclass(frozen=True, kw_only=True)
class TaskField(Field):
    """One task, searchable. With `task_set`, the picker only lists tasks from the set chosen in
    the field of that name. The value is the instance id."""

    task_set: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunField(Field):
    """A loaded run. The value is its id."""


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

    workspace: Path
    data: Mapping[str, object]

    def __getitem__(self, name: str) -> object:
        return self.data[name]

    def text(self, name: str) -> str | None:
        value = self.data.get(name)
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
    """One action in the Workbench. Subclass it, declare the class attributes and `build`, then
    `register` it. See the guide in `gauntlet.tui.workbench`.

    `cost` is the one line on what a run costs (Docker, network, minutes, disk). `after` opens what
    a succeeded job made; the default opens its first output.
    """

    action_id: ClassVar[str]
    title: ClassVar[str]
    group: ClassVar[ActionGroup]
    description: ClassVar[str]
    cost: ClassVar[str] = ""
    needs: ClassVar[tuple[Need, ...]] = ()
    fields: ClassVar[tuple[Field, ...]] = ()

    def build(self, values: Values) -> JobSpec:
        """The job these values make. Raise `BuildError` (any `ValueError`) to refuse with a reason."""
        raise NotImplementedError

    def after(self, job: JobRecord, app: GauntletApp) -> bool:
        """Open what `job` made. Returns False when there's nothing to open."""
        for output in job.spec.outputs:
            app.open_output(output)
            return True
        return False


_REGISTRY: dict[str, type[ActionForm]] = {}


def register(form: type[ActionForm]) -> type[ActionForm]:
    """Add an action to the Workbench. Use it as a class decorator."""
    if form.action_id in _REGISTRY and _REGISTRY[form.action_id] is not form:
        raise ValueError(f"two actions are called {form.action_id}")
    if form.group not in dict(GROUPS):
        raise ValueError(f"{form.action_id} is in an unknown group {form.group}")
    _REGISTRY[form.action_id] = form
    return form


def registered() -> tuple[type[ActionForm], ...]:
    """Every registered action, grouped in `GROUPS` order, each group in the order it was added."""
    order = {group: index for index, (group, _) in enumerate(GROUPS)}
    return tuple(sorted(_REGISTRY.values(), key=lambda form: order[form.group]))


def form_for(action_id: str, catalogue: Sequence[type[ActionForm]] | None = None) -> type[ActionForm] | None:
    for form in catalogue if catalogue is not None else _REGISTRY.values():
        if form.action_id == action_id:
            return form
    return None
