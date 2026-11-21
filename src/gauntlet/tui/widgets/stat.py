"""`Stat`: one headline number with its label, for the top of a screen."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text

from .themed import Themed


class Stat(Themed):
    """A bold value over a muted label, with an optional note after the value."""

    DEFAULT_CSS = """
    Stat {
        height: 2;
        width: auto;
    }
    """

    def __init__(
        self,
        value: str | Text,
        label: str,
        *,
        note: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.value = value
        self.label = label
        self.note = note

    def render(self) -> RenderableType:
        value = self.value.copy() if isinstance(self.value, Text) else Text(self.value, end="")
        value.stylize("bold")
        if self.note:
            value.append_text(self.look.muted(f" {self.note}"))
        value.append("\n")
        value.append_text(self.look.muted(self.label))
        return value
