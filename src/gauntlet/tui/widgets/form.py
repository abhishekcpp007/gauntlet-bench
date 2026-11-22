"""`FormView`: an `ActionForm` drawn as labelled fields, checked as you go, built into a `JobSpec`.

Each field is a `FieldRow`: the label in a fixed dim column, the input beside it, and a note under
it that holds the hint, or the error once the field is checked. A field is checked when you leave
it, and every field is checked on review. `ctrl+r` (or the Review button, or `enter` on the last
text field) checks them all, focuses the first bad one, then calls the form's `build`. A
`ValueError` from `build` shows its message at the top. A good build posts `FormView.Reviewed`
with the spec; the screen opens the confirm step from there.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import partial
from typing import cast

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import DescendantBlur, Resize
from textual.message import Message
from textual.widgets import Button, Input, Select, SelectionList, Static, Switch
from textual.widgets.selection_list import Selection
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..jobtypes import ActionInfo, JobSpec
from ..models import DataSource
from ..theme import ERROR, WARNING
from ..workbench.base import (
    ActionForm,
    Choice,
    ChoiceField,
    Field,
    FieldError,
    MultiChoiceField,
    PathField,
    RunField,
    SwitchField,
    TaskField,
    TaskSetField,
    Values,
    place_prefill,
)
from ..workspace import Workspace
from .pickers import PathPicker, Picker, run_choices, task_choices, task_set_choices
from .states import describe_error
from .themed import Themed

Control = Input | Select[str] | Switch | SelectionList[str] | PathPicker | Picker
OPTIONS_GROUP = "options"
PREFILL_GROUP = "prefill"
STACK_BELOW = 72
NO_WORKSPACE = "The workspace isn't ready yet. It's known once the machine check finishes."


class FieldNote(Themed):
    """The hint under a field, or its error as a mark, a word and the sentence."""

    DEFAULT_CSS = """
    FieldNote {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(self, hint: str) -> None:
        super().__init__()
        self.hint = hint
        self.error: str | None = None

    def show_error(self, error: str | None) -> None:
        self.error = error
        self.set_class(error is not None, "-error")
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        if self.error is not None:
            text = look.mark(ERROR)
            text.append("  ")
            text.append_text(fmt.safe_text(self.error, single_line=True, style=look.palette.bad))
            return text
        return look.muted(self.hint)


class FormBanner(Themed):
    """One line over the fields: why the job can't start, or why `build` refused."""

    DEFAULT_CSS = """
    FormBanner {
        height: auto;
        display: none;
        margin-bottom: 1;
    }
    FormBanner.-shown {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.blocked: str | None = None
        self.error: str | None = None

    def show(self, *, blocked: str | None = None, error: str | None = None) -> None:
        self.blocked = blocked
        self.error = error
        self.set_class(bool(blocked or error), "-shown")
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="")
        if self.blocked:
            text.append_text(look.mark(WARNING, word=False))
            text.append(" Can't start yet  ", style=look.style("warn", bold=True))
            text.append_text(fmt.safe_text(self.blocked, single_line=True))
        if self.error:
            if self.blocked:
                text.append("\n")
            text.append_text(look.mark(ERROR, word=False))
            text.append(" Can't build this job  ", style=look.style("bad", bold=True))
            text.append_text(fmt.safe_text(self.error, single_line=True))
        return text


def make_control(field: Field, source: Callable[[], DataSource]) -> Control:
    """The input widget for a field."""
    if isinstance(field, SwitchField):
        return Switch(field.default, animate=False)
    if isinstance(field, ChoiceField):
        options = [(fmt.one_line(c.label), c.value) for c in field.choices]
        value = field.default if field.default is not None else Select.NULL
        return Select(options, value=value, allow_blank=not field.required, compact=True, prompt="choose")
    if isinstance(field, MultiChoiceField):
        chosen = set(field.default) if field.default is not None else None
        return SelectionList[str](
            *(Selection(c.label, c.value, chosen is None or c.value in chosen) for c in field.choices),
            compact=True,
        )
    if isinstance(field, PathField):
        return PathPicker(field.kind, value=field.default, placeholder=field.placeholder)
    if isinstance(field, TaskSetField):
        return Picker(field.label, lambda: task_set_choices(source()), prompt="pick a task set")
    if isinstance(field, TaskField):
        return Picker(field.label, lambda: task_choices(source()), prompt="pick a task")
    if isinstance(field, RunField):
        return Picker(field.label, lambda: run_choices(source()), prompt="pick a run")
    default = getattr(field, "default", "")
    placeholder = getattr(field, "placeholder", "")
    return Input("" if default is None else str(default), placeholder=placeholder, compact=True)


def raw_value(control: Control) -> object:
    """What the control holds, before the field checks it."""
    if isinstance(control, Select):
        return None if control.value is Select.NULL else control.value
    if isinstance(control, SelectionList):
        return tuple(control.selected)
    if isinstance(control, Picker):
        return control.choice
    return control.value


class FieldRow(Vertical):
    """A label, an input and a note. Checks its field when focus leaves it."""

    DEFAULT_CSS = """
    FieldRow {
        height: auto;
        margin-bottom: 1;
    }
    FieldRow > .field-line {
        height: auto;
    }
    FieldRow .field-label {
        width: 20;
        color: $foreground-muted;
        padding-right: 2;
    }
    FieldRow.-required .field-label {
        color: $foreground;
    }
    FieldRow .field-input {
        width: 1fr;
        max-width: 64;
    }
    FieldRow FieldNote {
        padding-left: 20;
        max-width: 84;
    }
    FieldRow Input.field-input, FieldRow PathInput {
        background: $panel;
        padding: 0 1;
    }
    FieldRow Input.field-input:focus, FieldRow PathInput:focus {
        background: $block-cursor-background;
    }
    FieldRow Switch {
        border: none;
        height: 1;
        width: auto;
        padding: 0;
        background: transparent;
    }
    FieldRow Switch:focus {
        border: none;
        background: $block-cursor-background;
    }
    FieldRow SelectionList {
        height: auto;
        max-height: 12;
        background: $panel;
    }
    FieldRow Select {
        width: 1fr;
    }
    """

    def __init__(self, field: Field, control: Control) -> None:
        super().__init__(id=f"field-{field.name}", classes="-required" if field.required else "")
        self.field = field
        self.control = control
        self.note = FieldNote(field.hint)
        self.checked = False

    def compose(self) -> ComposeResult:
        with Horizontal(classes="field-line"):
            yield Static(self.field.label, classes="field-label", markup=False)
            self.control.add_class("field-input")
            yield self.control
        yield self.note

    def on_mount(self) -> None:
        field = self.field
        options = getattr(field, "options", None)
        if options is not None:
            source = self.form.source
            self.run_worker(
                lambda: tuple(options(source())), thread=True, group=OPTIONS_GROUP, exit_on_error=False
            )

    @property
    def form(self) -> FormView:
        for node in self.ancestors:
            if isinstance(node, FormView):
                return node
        raise LookupError("a FieldRow lives in a FormView")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != OPTIONS_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS:
            self.set_choices(cast("tuple[Choice, ...]", event.worker.result))
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.note.show_error(f"Couldn't load the choices: {describe_error(event.worker.error)}")

    def set_choices(self, choices: tuple[Choice, ...]) -> None:
        control = self.control
        field = self.field
        if isinstance(control, SelectionList) and isinstance(field, MultiChoiceField):
            chosen = set(field.default) if field.default is not None else None
            control.clear_options()
            control.add_options(
                [Selection(c.label, c.value, chosen is None or c.value in chosen) for c in choices]
            )
        elif isinstance(control, Select) and isinstance(field, ChoiceField):
            control.set_options([(fmt.one_line(c.label), c.value) for c in choices])
            if field.default is not None and field.default in {c.value for c in choices}:
                control.value = field.default

    @property
    def raw(self) -> object:
        return raw_value(self.control)

    def focus_control(self) -> None:
        target = self.control.input if isinstance(self.control, PathPicker) else self.control
        target.focus()

    def validate(self) -> tuple[bool, object]:
        """Check the field and show the result. Returns whether it's good, and its value."""
        self.checked = True
        try:
            value = self.field.check(self.raw)
        except FieldError as error:
            self.note.show_error(str(error))
            return False, None
        self.note.show_error(None)
        return True, value

    def on_descendant_blur(self, _event: DescendantBlur) -> None:
        self.call_after_refresh(self._left)

    def _left(self) -> None:
        if self.app.screen is not self.screen or not self.is_mounted:
            return
        focused = self.screen.focused
        if focused is None or self not in focused.ancestors_with_self:
            self.validate()

    def recheck(self) -> None:
        """Check again as the value changes, once the field has shown an error."""
        if self.checked and self.note.error is not None:
            self.validate()

    def on_input_changed(self) -> None:
        self.recheck()

    def on_picker_changed(self) -> None:
        self.recheck()

    def on_select_changed(self) -> None:
        self.recheck()

    def on_selection_list_selected_changed(self) -> None:
        self.recheck()


class ReviewButton(Button):
    """The one primary action on a form."""


class FormView(VerticalScroll):
    """An `ActionForm`'s fields. See the module docstring."""

    HELP_GROUP = "Form"
    BINDINGS = [Binding("ctrl+r", "review", "Review")]

    DEFAULT_CSS = """
    FormView {
        height: 1fr;
        padding: 1 2 0 2;
        background: $surface;
    }
    FormView > .form-actions {
        height: auto;
        margin: 0 0 1 20;
    }
    FormView ReviewButton {
        min-width: 12;
    }
    FormView .form-intro {
        display: none;
        color: $foreground-muted;
        margin-bottom: 1;
    }
    FormView.-stacked .form-intro {
        display: block;
    }
    FormView.-stacked FieldRow > .field-line {
        layout: vertical;
    }
    FormView.-stacked FieldRow .field-label {
        width: auto;
    }
    FormView.-stacked FieldRow FieldNote {
        padding-left: 0;
    }
    FormView.-stacked > .form-actions {
        margin: 0 0 1 0;
    }
    FormView .form-keys {
        width: auto;
        padding: 0 2;
        color: $foreground-muted;
    }
    """

    class Reviewed(Message):
        """Every field checked out and `build` made `spec`."""

        def __init__(self, view: FormView, spec: JobSpec) -> None:
            super().__init__()
            self.view = view
            self.spec = spec

        @property
        def control(self) -> FormView:
            return self.view

    def __init__(
        self,
        form: ActionForm,
        *,
        source: Callable[[], DataSource],
        info: ActionInfo | None = None,
        workspace: Workspace | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.form = form
        self.info = info
        self.source = source
        self.workspace = workspace
        self.blocked: str | None = None
        self.rows: list[FieldRow] = []
        self.linked: dict[str, str | None] = {}

    def compose(self) -> ComposeResult:
        yield Static(self.info.description if self.info else "", classes="form-intro", markup=False)
        yield FormBanner()
        self.rows = [FieldRow(field, make_control(field, self.source)) for field in self.form.fields]
        yield from self.rows
        with Horizontal(classes="form-actions"):
            yield ReviewButton("Review", variant="primary", compact=True)
            yield Static("ctrl+r", classes="form-keys", markup=False)

    def on_resize(self, event: Resize) -> None:
        self.set_class(event.size.width < STACK_BELOW, "-stacked")

    @property
    def banner(self) -> FormBanner:
        return self.query_one(FormBanner)

    def row(self, name: str) -> FieldRow:
        return self.query_one(f"#field-{name}", FieldRow)

    def focus_first(self) -> None:
        if self.rows:
            self.rows[0].focus_control()
        else:
            self.query_one(ReviewButton).focus()

    def set_blocked(self, reason: str | None) -> None:
        self.blocked = reason
        self.banner.show(blocked=reason, error=self.banner.error)

    def check_all(self) -> dict[str, object] | None:
        """Check every field. The values by name, or None after focusing the first bad field."""
        values: dict[str, object] = {}
        first_bad: FieldRow | None = None
        for row in self.rows:
            ok, value = row.validate()
            if ok:
                values[row.field.name] = value
            elif first_bad is None:
                first_bad = row
        if first_bad is not None:
            first_bad.focus_control()
            first_bad.scroll_visible(animate=False)
            return None
        return values

    def review(self) -> JobSpec | None:
        """Check, build and post `Reviewed`. Returns the spec, or None when something's wrong."""
        self.banner.show(blocked=self.blocked)
        values = self.check_all()
        if values is None:
            return None
        if self.workspace is None:
            self.banner.show(blocked=self.blocked, error=NO_WORKSPACE)
            return None
        try:
            spec = self.form.build(Values(self.workspace, values))
        except ValueError as error:
            self.banner.show(blocked=self.blocked, error=str(error))
            self.scroll_home(animate=False)
            return None
        if self.blocked:
            self.scroll_home(animate=False)
            self.app.bell()
            return None
        self.post_message(self.Reviewed(self, spec))
        return spec

    def action_review(self) -> None:
        self.review()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if isinstance(event.button, ReviewButton):
            event.stop()
            self.review()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        rows = [row for row in self.rows if event.input in row.query("*")]
        if rows and rows[0] is self.rows[-1]:
            self.review()
        else:
            self.screen.focus_next()

    def tasks_in(self, task_set: str | None) -> tuple[Choice, ...]:
        return task_choices(self.source(), task_set)

    def on_picker_changed(self, event: Picker.Changed) -> None:
        rows = [row for row in self.rows if row.control is event.picker]
        if not rows or not isinstance(rows[0].field, TaskSetField):
            return
        name = rows[0].field.name
        if name not in self.linked or self.linked[name] != event.value:
            self.link_tasks(name, event.value)

    def link_tasks(self, name: str, task_set: str | None) -> None:
        """Point every task field that lists from the task set field `name` at `task_set`."""
        self.linked[name] = task_set
        for row in self.rows:
            field = row.field
            if isinstance(field, TaskField) and field.task_set == name and isinstance(row.control, Picker):
                row.control.set_fetch(
                    partial(self.tasks_in, task_set),
                    prompt="pick a task" if task_set else "pick a task set first",
                )

    def prefill(self, values: Mapping[str, str]) -> None:
        """Fill fields by what the values mean (`task_set`, `task`, `run`, `patch`), not by their
        names, then focus the first field still empty. A path goes in at once. A picker looks its
        choice up in a thread, and a value it can't find is left out, like a key with no field."""
        placed = place_prefill(self.form.fields, values)
        for field, value in placed.values():
            control = self.row(field.name).control
            if isinstance(control, PathPicker):
                control.input.value = value
        if any(isinstance(field, TaskSetField | TaskField | RunField) for field, _ in placed.values()):
            self.run_worker(
                partial(self.find_choices, placed),
                thread=True,
                group=PREFILL_GROUP,
                exclusive=True,
                exit_on_error=False,
            )
        else:
            self.focus_empty()

    def find_choices(self, placed: Mapping[str, tuple[Field, str]]) -> tuple[tuple[Field, Choice], ...]:
        """The choices for the picker fields in `placed`, task set first. Runs in a thread. A task
        given without its set brings its set along when its field lists from one."""
        source = self.source()
        found: list[tuple[Field, Choice]] = []
        task_set = placed.get("task_set")
        task = placed.get("task")
        set_field = task_set[0] if task_set else None
        set_id = task_set[1] if task_set else None
        if task is not None and set_field is None and isinstance(task[0], TaskField) and task[0].task_set:
            linked = next((f for f in self.form.fields if f.name == task[0].task_set), None)
            if isinstance(linked, TaskSetField):
                try:
                    set_field, set_id = linked, source.task(task[1]).row.dataset_id
                except Exception:  # a task that isn't loaded leaves both pickers alone
                    return ()
        if set_field is not None:
            chosen = next((c for c in task_set_choices(source) if c.value == set_id), None)
            if chosen is None:
                set_id = None
            else:
                found.append((set_field, chosen))
        if task is not None:
            listed = set_id if isinstance(task[0], TaskField) and task[0].task_set else None
            chosen = next((c for c in task_choices(source, listed) if c.value == task[1]), None)
            if chosen is not None:
                found.append((task[0], chosen))
        if (run := placed.get("run")) is not None:
            chosen = next((c for c in run_choices(source) if c.value == run[1]), None)
            if chosen is not None:
                found.append((run[0], chosen))
        return tuple(found)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.group != PREFILL_GROUP:
            return
        event.stop()
        if event.state == WorkerState.SUCCESS:
            self.apply_choices(cast("tuple[tuple[Field, Choice], ...]", event.worker.result))
        elif event.state == WorkerState.ERROR:
            self.focus_empty()

    def apply_choices(self, found: tuple[tuple[Field, Choice], ...]) -> None:
        for field, choice in found:
            control = self.row(field.name).control
            if not isinstance(control, Picker):
                continue
            control.pick(choice)
            if isinstance(field, TaskSetField):
                self.link_tasks(field.name, choice.value)
        self.focus_empty()

    def focus_empty(self) -> None:
        """Focus the first required field that's still empty, or Review when none is."""
        for row in self.rows:
            if row.field.required and row.raw in (None, "", ()):
                row.focus_control()
                return
        self.query_one(ReviewButton).focus()
