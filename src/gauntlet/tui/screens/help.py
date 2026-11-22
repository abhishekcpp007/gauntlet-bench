"""The help screen (`?`): every key that works where you pressed it, grouped, built from the live
bindings so it can't go stale.

A screen names its own group with `HELP_GROUP` (else it's "This screen"). A screen with
`HELP_EVERY_PANE` also lists the keys of its panes that don't have focus, like the Workbench's
form while you're in its action list. A viewer screen's Workbench keys go under "Workbench"."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical, VerticalScroll
from textual.dom import DOMNode
from textual.screen import ModalScreen, Screen
from textual.widgets import Input, Tabs

from ..widgets.themed import Themed

EVERYWHERE = "Everywhere"
THIS_SCREEN = "This screen"
WORKBENCH_KEYS = "Workbench"
WORKBENCH_ACTION = "app.workbench("
OWN_PACKAGE = "gauntlet."
TEXTUAL_GROUPS: tuple[tuple[type[DOMNode], str], ...] = (
    (Tabs, "Tabs"),
    (Input, "Text box"),
    (ScrollableContainer, "Scrolling"),
)
KEY_GAP = 2
HELP_WIDTH = 104
HELP_FRAME = 6
COLUMN_WIDTH = 30


@dataclass(frozen=True, slots=True)
class KeyHelp:
    keys: str
    description: str


def group_name(node: DOMNode) -> str:
    """What a binding's owner is called in help: a widget's `HELP_GROUP`, or where it applies."""
    if isinstance(node, App):
        return EVERYWHERE
    if isinstance(node, Screen):
        return str(getattr(node, "HELP_GROUP", THIS_SCREEN))
    if hasattr(node, "HELP_GROUP"):
        return str(node.HELP_GROUP)
    for kind, name in TEXTUAL_GROUPS:
        if isinstance(node, kind):
            return name
    return type(node).__name__


def own_bindings(node: DOMNode) -> list[Binding]:
    """The bindings this app's own classes give `node`, leaving out the ones Textual adds."""
    found: list[Binding] = []
    for kind in type(node).__mro__:
        if kind.__module__.startswith(OWN_PACKAGE):
            found.extend(Binding.make_bindings(kind.__dict__.get("BINDINGS", ())))
    return found


def other_panes(screen: Screen) -> list[tuple[DOMNode, Binding]]:
    """The keys of every widget on `screen` that names a help group, focused or not."""
    return [
        (node, binding)
        for node in screen.query("*")
        if hasattr(node, "HELP_GROUP")
        for binding in own_bindings(node)
    ]


def collect(screen: Screen) -> list[tuple[str, list[KeyHelp]]]:
    """The bindings active on `screen`, grouped by owner, closest first. Keys bound to the same
    action are shown together, like `esc/backspace`."""
    app = screen.app
    groups: dict[str, dict[str, list[str]]] = {}
    descriptions: dict[tuple[str, str], str] = {}
    found = [(active.node, active.binding) for active in screen.active_bindings.values()]
    if getattr(screen, "HELP_EVERY_PANE", False):
        found += other_panes(screen)
    for node, binding in found:
        if not binding.description:
            continue
        name = WORKBENCH_KEYS if binding.action.startswith(WORKBENCH_ACTION) else group_name(node)
        keys = groups.setdefault(name, {}).setdefault(binding.action, [])
        display = app.get_key_display(binding)
        if display not in keys:
            keys.append(display)
        descriptions[(name, binding.action)] = binding.description
    own = group_name(screen)
    ordered = sorted(groups, key=lambda g: (g == EVERYWHERE, g == own))
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


def per_row(width: int, groups: int) -> int:
    """How many groups fit side by side in a help box on a terminal `width` wide."""
    room = min(width, HELP_WIDTH) - HELP_FRAME
    return max(1, min(groups, room // COLUMN_WIDTH))


class HelpScreen(ModalScreen[None]):
    """Keys for the screen underneath, a column per group, in as many rows as the width needs.
    `esc`, `?` or `q` closes it."""

    DEFAULT_CSS = """
    HelpScreen .help-row {
        height: auto;
        margin-bottom: 1;
    }
    #help-columns {
        layout: vertical;
    }
    """

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
            with Vertical(id="help-columns"):
                size = per_row(self.app.size.width, len(self.groups))
                for start in range(0, len(self.groups), size):
                    with Horizontal(classes="help-row"):
                        for name, keys in self.groups[start : start + size]:
                            yield KeyTable(name, keys)
