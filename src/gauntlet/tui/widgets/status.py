"""`StatusBadge` and `RewardText`: one status, or one reward, in the fixed symbols and colours."""

from __future__ import annotations

from rich.console import RenderableType
from textual.reactive import reactive

from ..models import Severity, Verdict
from ..theme import SEVERITIES, VERDICTS, Mark, leak_mark, resolved_mark
from .themed import Themed


class StatusBadge(Themed):
    """A `Mark` as symbol and word, like `● cheating`. Build one from a mark or a helper."""

    DEFAULT_CSS = """
    StatusBadge {
        width: auto;
        height: 1;
    }
    """

    mark: reactive[Mark | None] = reactive(None, layout=True)

    def __init__(self, mark: Mark, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.set_reactive(StatusBadge.mark, mark)

    @classmethod
    def verdict(cls, verdict: Verdict, **kwargs: str) -> StatusBadge:
        return cls(VERDICTS[verdict], **kwargs)

    @classmethod
    def resolved(cls, resolved: bool, **kwargs: str) -> StatusBadge:
        return cls(resolved_mark(resolved), **kwargs)

    @classmethod
    def severity(cls, severity: Severity, **kwargs: str) -> StatusBadge:
        return cls(SEVERITIES[severity], **kwargs)

    @classmethod
    def leak_check(cls, ok: bool, **kwargs: str) -> StatusBadge:
        return cls(leak_mark(ok), **kwargs)

    def render(self) -> RenderableType:
        return self.look.mark(self.mark) if self.mark else ""


class RewardText(Themed):
    """A reward on the diverging scale, always signed with two decimals: `+0.97`, `-1.00`."""

    DEFAULT_CSS = """
    RewardText {
        width: auto;
        height: 1;
    }
    """

    value: reactive[float | None] = reactive(None, layout=True)

    def __init__(
        self, value: float | None, *, bold: bool = False, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.bold = bold
        self.set_reactive(RewardText.value, value)

    def render(self) -> RenderableType:
        return self.look.reward(self.value, bold=self.bold)
