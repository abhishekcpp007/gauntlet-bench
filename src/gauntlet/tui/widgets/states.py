"""What a pane shows when it has nothing, when a load failed, and while it loads."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text
from textual.timer import Timer

from ..format import safe_text
from ..models import NotFound
from ..theme import ERROR
from .themed import Themed

SPINNER_FPS = 12


@dataclass(frozen=True, slots=True)
class Empty:
    """Why a list is empty, and what to do about it."""

    title: str
    hint: str = ""


def describe_error(error: BaseException) -> str:
    """One plain line for a failed load. Never a traceback."""
    if isinstance(error, NotFound):
        return f"Nothing called {error.args[0] if error.args else 'that'} was loaded."
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


class EmptyState(Themed):
    """A centred title with a muted hint under it."""

    DEFAULT_CSS = """
    EmptyState {
        height: 1fr;
        min-height: 3;
        content-align: center middle;
        text-align: center;
        padding: 1 2;
    }
    """

    def __init__(self, empty: Empty, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.empty = empty

    def show(self, empty: Empty) -> None:
        self.empty = empty
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        text = Text(self.empty.title, style="bold", end="")
        if self.empty.hint:
            text.append("\n")
            text.append_text(self.look.muted(self.empty.hint))
        return text


class ErrorState(Themed):
    """A load that failed: what failed, and the one-line reason. The app keeps running."""

    DEFAULT_CSS = """
    ErrorState {
        height: 1fr;
        min-height: 3;
        content-align: center middle;
        text-align: center;
        padding: 1 2;
    }
    """

    def __init__(self, title: str, message: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.title = title
        self.message = message

    def render(self) -> RenderableType:
        text = self.look.mark(ERROR, word=False)
        text.append(f" {self.title}", style=self.look.style("bad", bold=True))
        text.append("\n")
        text.append_text(safe_text(self.message, single_line=True))
        return text


class Loading(Themed):
    """A spinner and what's loading. Spins in ASCII under --ascii."""

    DEFAULT_CSS = """
    Loading {
        height: 1fr;
        min-height: 1;
        content-align: center middle;
    }
    """

    def __init__(self, what: str, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.what = what
        self._frame = 0
        self._timer: Timer | None = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(1 / SPINNER_FPS, self._spin)

    def _spin(self) -> None:
        self._frame += 1
        self.refresh()

    def render(self) -> RenderableType:
        frames = self.look.glyphs.spinner
        text = self.look.accent(frames[self._frame % len(frames)])
        text.append_text(self.look.muted(f" Loading {self.what}{self.look.glyphs.ellipsis}"))
        return text
