"""The help screen (`?`): every key that works where you pressed it, grouped, built from the live
bindings so it can't go stale."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.dom import DOMNode
from textual.screen import ModalScreen, Screen

from ..widgets.themed import Themed

EVERYWHERE = "Everywhere"
THIS_SCREEN = "This screen"
KEY_GAP = 2


@dataclass(frozen=True, slots=True)
class KeyHelp:
    keys: str
    description: str


def group_name(node: DOMNode) -> str:
    """What a binding's owner is called in help: a widget's `HELP_GROUP`, or where it applies."""
    if isinstance(node, App):
        return EVERYWHERE
    if isinstance(node, Screen):
        return THIS_SCREEN
    return getattr(node, "HELP_GROUP", type(node).__name__)


def collect(screen: Screen) -> list[tuple[str, list[KeyHelp]]]:
    """The bindings active on `screen`, grouped by owner, closest first. Keys bound to the same
    action are shown together, like `esc/backspace`."""
    app = screen.app
    groups: dict[str, dict[str, list[str]]] = {}
    descriptions: dict[tuple[str, str], str] = {}
    for active in screen.active_bindings.values():
        binding: Binding = active.binding
        if not binding.description:
            continue
        name = group_name(active.node)
        keys = groups.setdefault(name, {}).setdefault(binding.action, [])
        display = app.get_key_display(binding)
        if display not in keys:
            keys.append(display)
        descriptions[(name, binding.action)] = binding.description
    ordered = sorted(groups, key=lambda g: (g == EVERYWHERE, g == THIS_SCREEN))
    return [
        (
            name,
            [KeyHelp("/".join(keys), descriptions[(name, action)]) for action, keys in groups[name].items()],
        )
        for name in ordered
    ]


class KeyTable(Themed):
    """One group of keys under its name."""

    DEFAULT_CSS = """
    KeyTable {
        height: auto;
    }
    """

    def __init__(self, name: str, keys: list[KeyHelp]) -> None:
        super().__init__()
        self.group = name
        self.keys = keys

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, KEY_GAP))
        grid.add_column(width=max((len(k.keys) for k in self.keys), default=0), justify="right", no_wrap=True)
        grid.add_column()
        grid.add_row("", Text(self.group, style="bold"))
        for key in self.keys:
            grid.add_row(look.accent(key.keys), key.description)
        return grid


class HelpScreen(ModalScreen[None]):
    """Keys for the screen underneath, one column per group. `esc`, `?` or `q` closes it."""

    BINDINGS = [
        Binding("escape,question_mark,q", "dismiss", "Close", show=False),
    ]

    def __init__(self, under: Screen) -> None:
        super().__init__()
        self.groups = collect(under)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box", classes="pane") as box:
            box.border_title = "Keys"
            box.border_subtitle = "esc closes"
            with Horizontal(id="help-columns"):
                for name, keys in self.groups:
                    yield KeyTable(name, keys)
