"""The app's frame: `TopBar` (wordmark, breadcrumbs, what's loaded) and `NavBar` (destinations)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import RenderableType
from rich.style import Style
from rich.text import Text

from .. import format as fmt
from .themed import Themed

WORDMARK = "GAUNTLET"
BAR_PADDING = 1
CRUMB_MIN = 6
NAV_GAP = 2


@dataclass(frozen=True, slots=True)
class Destination:
    key: str
    label: str
    mode: str


class TopBar(Themed):
    """`GAUNTLET  Runs › golden › tomli-318` on the left and `147 tasks · 4 runs` on the right.

    The last crumb is the current screen and is cut in the middle first when space runs out.
    """

    DEFAULT_CSS = """
    TopBar {
        height: 1;
        width: 1fr;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.crumbs: tuple[str, ...] = ()
        self.loaded = ""

    def show(self, crumbs: Sequence[str], loaded: str) -> None:
        self.crumbs = tuple(crumbs)
        self.loaded = loaded
        self.refresh()

    def render(self) -> RenderableType:
        look = self.look
        width = max(self.size.width - 2 * BAR_PADDING, 0)
        right = look.muted(self.loaded)
        left = Text(end="", no_wrap=True)
        left.append_text(look.accent(WORDMARK, bold=True))
        sep = f" {look.glyphs.crumb} "
        room = width - left.cell_len - 2 - (right.cell_len + 2 if self.loaded else 0)
        crumbs = list(self.crumbs)
        while crumbs and cell_len(sep.join(crumbs)) > room:
            longest = max(range(len(crumbs)), key=lambda i: len(crumbs[i]))
            if len(crumbs[longest]) <= CRUMB_MIN:
                crumbs.pop(0)
                continue
            crumbs[longest] = fmt.middle(crumbs[longest], len(crumbs[longest]) - 1, look.glyphs.ellipsis)
        if crumbs:
            left.append("  ")
            for index, crumb in enumerate(crumbs):
                if index:
                    left.append_text(look.muted(sep))
                last = index == len(crumbs) - 1
                left.append_text(fmt.safe_text(crumb, single_line=True, style="bold" if last else ""))
        gap = max(width - left.cell_len - right.cell_len, 1)
        line = Text(end="", no_wrap=True, overflow="crop")
        line.append_text(left)
        line.append(" " * gap)
        line.append_text(right)
        return line


class NavBar(Themed):
    """`1 Overview  2 Tasks  3 Runs  4 Reference`, with the active destination highlighted."""

    DEFAULT_CSS = """
    NavBar {
        height: 1;
        width: 1fr;
        padding: 0 1;
        background: $surface;
    }
    """

    def __init__(self, destinations: Sequence[Destination], active: str) -> None:
        super().__init__()
        self.destinations = tuple(destinations)
        self.active = active

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="", no_wrap=True, overflow="crop")
        for destination in self.destinations:
            on = destination.mode == self.active
            text.append(f" {destination.key} ", style=look.style("accent" if on else "muted"))
            label = look.style("plain", bold=True) + Style(underline=True) if on else look.style("muted")
            text.append(destination.label, style=label)
            text.append(" " * NAV_GAP)
        return text
