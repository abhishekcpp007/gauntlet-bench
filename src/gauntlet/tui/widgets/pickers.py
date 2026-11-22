"""Pickers for forms: a task set, a task, a run, or a path on disk.

`Picker` shows the chosen value on one line. `enter` opens `PickList`, a searchable list that
loads its choices in a thread, so a long list of tasks never blocks the screen. `PathPicker` is a
text box you can type a path into, with `ctrl+o` for `PathBrowser`, a folder tree built on
Textual's `DirectoryTree`. The `*_choices` functions turn `DataSource` records into choices.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.worker import Worker, WorkerState

from .. import format as fmt
from ..models import DataSource
from ..theme import look_for
from ..workbench.base import Choice, PathKind
from .states import Loading, describe_error
from .themed import Themed

Fetch = Callable[[], Sequence[Choice]]
DETAIL_GAP = 2
SUMMARY_ONLY = "summary only, no report"


def task_set_choices(source: DataSource) -> tuple[Choice, ...]:
    return tuple(Choice(d.id, d.id, fmt.plural(d.tasks, "task"), d.tasks_file) for d in source.datasets())


def task_choices(source: DataSource, task_set: str | None = None) -> tuple[Choice, ...]:
    return tuple(Choice(t.instance_id, t.instance_id, t.repo) for t in source.tasks(dataset=task_set))


def run_choices(source: DataSource) -> tuple[Choice, ...]:
    """Every run, with its size. A run with no results file says so before you pick it."""
    return tuple(
        Choice(r.id, r.id, run_detail(r.episodes, r.results_file), r.results_file) for r in source.runs()
    )


def run_detail(episodes: int, results_file: str | None) -> str:
    size = fmt.plural(episodes, "episode")
    return size if results_file is not None else f"{size}, {SUMMARY_ONLY}"


def choice_line(choice: Choice, look_muted: Callable[[str], Text]) -> Text:
    text = fmt.safe_text(choice.label, single_line=True)
    if choice.detail:
        text.append(" " * DETAIL_GAP)
        text.append_text(look_muted(fmt.one_line(choice.detail)))
    return text


class PickList(ModalScreen[Choice | None]):
    """Type to narrow the list, `enter` picks, `esc` closes without a change."""

    DEFAULT_CSS = """
    PickList {
        align: center middle;
    }
    PickList > Vertical {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: round $border;
        border-title-color: $text-primary;
        border-subtitle-color: $foreground-muted;
        background: $surface;
        padding: 0 1;
    }
    PickList Input {
        margin-bottom: 1;
        background: $boost;
    }
    PickList OptionList {
        height: auto;
        max-height: 20;
        border: none;
        background: $surface;
    }
    PickList Loading {
        height: 3;
    }
    PickList .pick-empty {
        color: $foreground-muted;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("down", "into_list", "Down", show=False),
    ]

    def __init__(self, title: str, fetch: Fetch, *, current: str | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.fetch = fetch
        self.current = current
        self.choices: tuple[Choice, ...] = ()

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = self.title_text
            box.border_subtitle = "enter picks · esc closes"
            yield Input(placeholder="type to search", compact=True)
            yield Loading("the choices")
            yield OptionList()
            yield Static("", classes="pick-empty", markup=False)

    def on_mount(self) -> None:
        self.query_one(OptionList).display = False
        self.query_one(".pick-empty").display = False
        self.run_worker(lambda: tuple(self.fetch()), thread=True, exit_on_error=False, name="choices")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name != "choices":
            return
        if event.state == WorkerState.SUCCESS:
            self.choices = tuple(event.worker.result or ())
            self.query_one(Loading).display = False
            self.show(self.query_one(Input).value)
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            self.query_one(Loading).display = False
            self.say(f"Couldn't load the choices: {describe_error(event.worker.error)}")

    def say(self, message: str) -> None:
        empty = self.query_one(".pick-empty", Static)
        empty.update(message)
        empty.display = True

    def show(self, needle: str) -> None:
        lowered = needle.strip().casefold()
        shown = [c for c in self.choices if lowered in c.label.casefold() or lowered in c.detail.casefold()]
        options = self.query_one(OptionList)
        muted = look_for(self).muted
        options.set_options([Option(choice_line(c, muted), id=c.value) for c in shown])
        options.display = bool(shown)
        self.query_one(".pick-empty").display = not shown
        if not shown:
            self.say("Nothing matches." if self.choices else "There's nothing to pick yet.")
        else:
            values = [c.value for c in shown]
            options.highlighted = values.index(self.current) if self.current in values else 0

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.show(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        options = self.query_one(OptionList)
        if options.option_count:
            options.action_select()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        picked = next((c for c in self.choices if c.value == event.option.id), None)
        self.dismiss(picked)

    def action_into_list(self) -> None:
        options = self.query_one(OptionList)
        if options.option_count:
            options.focus()

    def action_close(self) -> None:
        self.dismiss(None)


class Picker(Themed, can_focus=True):
    """One chosen `Choice`, or a dim prompt. `enter` opens the list. Posts `Picker.Changed`."""

    HELP_GROUP = "Form"
    BINDINGS = [
        Binding("enter,space", "open", "Choose"),
        Binding("delete", "clear", "Clear", show=False),
    ]

    DEFAULT_CSS = """
    Picker {
        height: 1;
        width: 1fr;
        background: $panel;
        padding: 0 1;
    }
    Picker:focus {
        background: $block-cursor-background;
    }
    Picker.-disabled {
        color: $foreground-muted;
    }
    """

    value: reactive[str | None] = reactive(None, layout=True)

    class Changed(Message):
        def __init__(self, picker: Picker, value: str | None) -> None:
            super().__init__()
            self.picker = picker
            self.value = value

        @property
        def control(self) -> Picker:
            return self.picker

    def __init__(
        self,
        title: str,
        fetch: Fetch,
        *,
        prompt: str = "choose",
        choice: Choice | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.title = title
        self.fetch = fetch
        self.prompt = prompt
        self.choice = choice
        self.set_reactive(Picker.value, None if choice is None else choice.value)

    def set_fetch(self, fetch: Fetch, *, prompt: str | None = None) -> None:
        """Change where the choices come from, which also clears the value."""
        self.fetch = fetch
        if prompt is not None:
            self.prompt = prompt
        self.pick(None)

    def pick(self, choice: Choice | None) -> None:
        """Choose `choice`, or nothing."""
        self.choice = choice
        self.value = None if choice is None else choice.value

    def watch_value(self, value: str | None) -> None:
        self.post_message(self.Changed(self, value))

    def render(self) -> RenderableType:
        if self.value is None:
            return self.look.muted(f"{self.prompt}{self.look.glyphs.ellipsis}  enter")
        return fmt.safe_text(self.value, single_line=True)

    def action_open(self) -> None:
        def picked(choice: Choice | None) -> None:
            if choice is not None:
                self.pick(choice)
            self.focus()

        self.app.push_screen(PickList(self.title, self.fetch, current=self.value), picked)

    def action_clear(self) -> None:
        self.pick(None)


class PathBrowser(ModalScreen[str | None]):
    """A folder tree from `root`. For a file, `enter` on it picks it. For a folder, `enter` opens
    it and `s` picks the highlighted one."""

    DEFAULT_CSS = """
    PathBrowser {
        align: center middle;
    }
    PathBrowser > Vertical {
        width: 80;
        max-width: 90%;
        height: 80%;
        border: round $border;
        border-title-color: $text-primary;
        border-subtitle-color: $foreground-muted;
        background: $surface;
    }
    PathBrowser DirectoryTree {
        height: 1fr;
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("s", "pick_folder", "Pick folder"),
        Binding("backspace", "up", "Up a folder"),
    ]

    def __init__(self, root: Path, kind: PathKind) -> None:
        super().__init__()
        self.root = root
        self.kind = kind

    def compose(self) -> ComposeResult:
        with Vertical() as box:
            box.border_title = f"Pick a {self.kind}"
            box.border_subtitle = (
                "enter picks · backspace goes up · esc closes"
                if self.kind == "file"
                else "enter opens · s picks · backspace goes up · esc closes"
            )
            yield DirectoryTree(self.root)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "pick_folder":
            return self.kind == "folder"
        return True

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()
        if self.kind == "file":
            self.dismiss(str(event.path))

    def action_pick_folder(self) -> None:
        tree = self.query_one(DirectoryTree)
        node = tree.cursor_node
        if node is not None and node.data is not None:
            path = Path(node.data.path)
            self.dismiss(str(path if path.is_dir() else path.parent))

    def action_up(self) -> None:
        tree = self.query_one(DirectoryTree)
        parent = Path(tree.path).resolve().parent
        tree.path = parent

    def action_close(self) -> None:
        self.dismiss(None)


class PathInput(Input):
    """The text box of a `PathPicker`."""

    HELP_GROUP = "Form"
    BINDINGS = [Binding("ctrl+o", "browse", "Browse")]

    def action_browse(self) -> None:
        picker = self.parent
        if isinstance(picker, PathPicker):
            picker.browse()


class BrowseHint(Static):
    """`ctrl+o browse` beside the box. Clicking it browses too."""

    def on_click(self) -> None:
        picker = self.parent
        if isinstance(picker, PathPicker):
            picker.browse()


class PathPicker(Horizontal):
    """Type a path, or press `ctrl+o` to browse for one."""

    DEFAULT_CSS = """
    PathPicker {
        height: 1;
        width: 1fr;
    }
    PathPicker > PathInput {
        width: 1fr;
    }
    PathPicker > .browse {
        width: auto;
        padding: 0 1;
        color: $foreground-muted;
    }
    """

    def __init__(
        self,
        kind: PathKind,
        *,
        value: str = "",
        placeholder: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.kind = kind
        self.initial = value
        self.placeholder = placeholder or f"a {kind} path"

    def compose(self) -> ComposeResult:
        yield PathInput(self.initial, placeholder=self.placeholder, compact=True)
        yield BrowseHint("ctrl+o browse", classes="browse", markup=False)

    @property
    def input(self) -> PathInput:
        return self.query_one(PathInput)

    @property
    def value(self) -> str:
        return self.input.value

    def start(self) -> Path:
        """Where the browser opens: the folder of what's typed, if it's there, else here."""
        typed = Path(self.value).expanduser() if self.value.strip() else Path.cwd()
        for candidate in (typed, typed.parent):
            if candidate.is_dir():
                return candidate
        return Path.cwd()

    def browse(self) -> None:
        def picked(path: str | None) -> None:
            if path is not None:
                self.input.value = path
            self.input.focus()

        self.app.push_screen(PathBrowser(self.start(), self.kind), picked)
