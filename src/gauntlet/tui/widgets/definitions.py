"""`Definitions`: terms and what they mean, as an aligned list."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import RenderableType
from rich.table import Table

from ..format import safe_text
from .themed import Themed

TERM_GAP = 2


@dataclass(frozen=True, slots=True)
class Definition:
    term: str
    what: str


class Definitions(Themed):
    """One row per `Definition`: the term in the accent colour and what it means beside it, wrapped
    in its own column. `numbered` adds a step number in front."""

    DEFAULT_CSS = """
    Definitions {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(
        self,
        items: Sequence[Definition],
        *,
        numbered: bool = False,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.items = tuple(items)
        self.numbered = numbered

    def render(self) -> RenderableType:
        look = self.look
        grid = Table.grid(padding=(0, TERM_GAP), expand=True)
        if self.numbered:
            grid.add_column(justify="right", no_wrap=True)
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        for index, item in enumerate(self.items, start=1):
            cells: list[RenderableType] = [
                look.accent(item.term),
                safe_text(item.what, style=look.style("plain")),
            ]
            if self.numbered:
                cells.insert(0, look.muted(f"{index}"))
            grid.add_row(*cells)
        return grid
