"""`FormNote`, a muted paragraph a form adds to its view with `ActionForm.extras`."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from weakref import WeakSet

from rich.console import RenderableType
from textual.widget import Widget

from .form import FormView
from .themed import Themed

Extras = Callable[[FormView], Sequence[tuple[Widget, str | None]]]
"""The widgets to add to a view, each with the name of the field it goes after (None: at the top)."""

_EXTENDED: WeakSet[FormView] = WeakSet()


class FormNote(Themed):
    """A muted paragraph inside a form, above its fields or between them."""

    DEFAULT_CSS = """
    FormNote {
        height: auto;
        margin-bottom: 1;
        max-width: 84;
    }
    """

    def __init__(self, text: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.text = text

    def render(self) -> RenderableType:
        return self.look.muted(self.text)
