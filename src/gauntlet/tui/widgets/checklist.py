"""`Checklist`: rows that pass or fail, each with a detail line (leak checks, rubric items)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from ..format import safe_text
from ..theme import FAILED, PASSED, Mark
from .themed import Themed

SYMBOL_GAP = 1


@dataclass(frozen=True, slots=True)
class CheckItem:
    label: str
    ok: bool
    detail: str = ""


class Checklist(Themed):
    """One row per item: the pass or fail mark, the label, and the detail in muted text below.

    Pass `failed=LEAK_FAILED` where a failure is an error rather than a plain miss.
    """

    DEFAULT_CSS = """
    Checklist {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(
        self,
        items: Sequence[CheckItem],
        *,
        passed: Mark = PASSED,
        failed: Mark = FAILED,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.items: tuple[CheckItem, ...] = tuple(items)
        self.passed = passed
        self.failed = failed

    @property
    def passing(self) -> int:
        return sum(item.ok for item in self.items)

    def set_items(self, items: Sequence[CheckItem]) -> None:
        self.items = tuple(items)
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        grid = Table.grid(padding=(0, SYMBOL_GAP), expand=True)
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        for item in self.items:
            mark = self.passed if item.ok else self.failed
            body = Text(end="")
            body.append(item.label, style="bold")
            body.append(f"  {mark.word}", style=self.look.style(mark.tone))
            if item.detail:
                body.append("\n")
                body.append_text(safe_text(item.detail, style=self.look.style("muted")))
            grid.add_row(self.look.mark(mark, word=False), body)
        return grid
