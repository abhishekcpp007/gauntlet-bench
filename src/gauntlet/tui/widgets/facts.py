"""`Facts`: a compact key and value block (ids, image, fingerprint, dates) you can copy from."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.binding import Binding
from textual.reactive import reactive

from ..format import safe_text
from ..theme import solid_color
from .messages import CopyRequested
from .themed import Themed

LABEL_GAP = 2


@dataclass(frozen=True, slots=True)
class Fact:
    """One row. `value` is shown; `copy` is what `c` copies (the plain value when None)."""

    label: str
    value: str | Text
    copy: str | None = None

    @property
    def copy_text(self) -> str:
        if self.copy is not None:
            return self.copy
        return self.value.plain if isinstance(self.value, Text) else self.value


class Facts(Themed, can_focus=True):
    """Labels in a muted column, values beside them. `up`/`down` pick a row, `c` copies it."""

    DEFAULT_CSS = """
    Facts {
        height: auto;
        width: 1fr;
    }
    """

    HELP_GROUP = "Details"
    BINDINGS = [
        Binding("c", "copy", "Copy"),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("up,k", "move(-1)", "Up", show=False),
    ]

    cursor: reactive[int] = reactive(0)

    def __init__(self, facts: Sequence[Fact], *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.facts: tuple[Fact, ...] = tuple(facts)

    def set_facts(self, facts: Sequence[Fact]) -> None:
        self.facts = tuple(facts)
        self.cursor = min(self.cursor, max(len(self.facts) - 1, 0))
        self.refresh(layout=True)

    @property
    def current(self) -> Fact | None:
        return self.facts[self.cursor] if self.facts else None

    def action_move(self, delta: int) -> None:
        if self.facts:
            self.cursor = max(0, min(len(self.facts) - 1, self.cursor + delta))

    def action_copy(self) -> None:
        if (fact := self.current) is not None:
            self.post_message(CopyRequested(fact.copy_text, fact.label.lower()))

    def render(self) -> RenderableType:
        label_width = max((len(f.label) for f in self.facts), default=0)
        grid = Table.grid(padding=(0, LABEL_GAP), expand=True)
        grid.add_column(width=label_width, no_wrap=True)
        grid.add_column(ratio=1, no_wrap=True, overflow=self.look.overflow)
        highlight = solid_color(self.app.theme_variables, "block-cursor-background")
        cursor = Style(bgcolor=highlight) if highlight else Style(reverse=True)
        for index, fact in enumerate(self.facts):
            value = fact.value if isinstance(fact.value, Text) else safe_text(fact.value, single_line=True)
            row_style = cursor if self.has_focus and index == self.cursor else None
            grid.add_row(self.look.muted(fact.label), value, style=row_style)
        return grid
