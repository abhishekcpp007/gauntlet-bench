"""`FilterBar`: the `/` search box above a list, its facet chips, and the `f` facet picker.

The bar posts `FilterBar.Changed` with the query and the chosen facets whenever either changes.
The screen re-queries its `DataSource` with them and calls `set_count` with the result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from .. import format as fmt
from ..models import Facet
from ..theme import PASSED, look_for
from .themed import Themed

ANY = "any"
_SEP = "\0"


@dataclass(frozen=True, slots=True)
class FacetGroup:
    """One way to narrow a list, like `repo`, with the values on offer and their counts."""

    key: str
    label: str
    facets: tuple[Facet, ...]


class FilterInput(Input):
    """The search box. `esc` clears it and hands focus back to the list, `enter` just hands it back."""

    HELP_GROUP = "Filter"
    BINDINGS = [
        Binding("escape", "clear", "Clear filter"),
        Binding("enter", "done", "Done", show=False),
        Binding("down", "done", "Done", show=False),
    ]

    def action_clear(self) -> None:
        self.value = ""
        self.screen.focus_next()

    def action_done(self) -> None:
        self.screen.focus_next()


class Prompt(Themed):
    """The `/` in front of the search box."""

    DEFAULT_CSS = """
    Prompt {
        width: 3;
        height: 1;
        padding: 0 0 0 1;
    }
    """

    def render(self) -> RenderableType:
        return self.look.accent("/", bold=True)


class Chips(Themed):
    """The active facets and the match count, on one line."""

    DEFAULT_CSS = """
    Chips {
        width: auto;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.facets: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self.count: tuple[int, int] | None = None

    def render(self) -> RenderableType:
        look = self.look
        text = Text(end="", no_wrap=True)
        for key, value in self.facets.items():
            text.append(f"{self.labels.get(key, key)} ", style=look.style("muted"))
            text.append(f"{value}  ", style=look.style("accent"))
        if self.count is not None:
            shown, total = self.count
            text.append(f"{fmt.count(shown)} of {fmt.count(total)}", style=look.style("muted"))
        return text


class FilterBar(Vertical):
    """`/` search plus facet chips. Give it `FacetGroup`s to make `f` work."""

    DEFAULT_CSS = """
    FilterBar {
        height: 1;
        layout: horizontal;
    }
    FilterBar > FilterInput {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0;
        background: $surface;
    }
    FilterBar > FilterInput:focus {
        background: $boost;
    }
    """

    class Changed(Message):
        def __init__(self, bar: FilterBar, query: str, facets: Mapping[str, str]) -> None:
            super().__init__()
            self.bar = bar
            self.query = query
            self.facets = dict(facets)

        @property
        def control(self) -> FilterBar:
            return self.bar

    def __init__(
        self,
        groups: Sequence[FacetGroup] = (),
        *,
        placeholder: str = "type to filter",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.groups: tuple[FacetGroup, ...] = tuple(groups)
        self.placeholder = placeholder
        self.facets: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Prompt()
        yield FilterInput(placeholder=self.placeholder, compact=True)
        yield Chips()

    @property
    def query(self) -> str:
        return self.query_one(FilterInput).value

    def focus_input(self) -> None:
        self.query_one(FilterInput).focus()

    def set_groups(self, groups: Sequence[FacetGroup]) -> None:
        self.groups = tuple(groups)
        chips = self.query_one(Chips)
        chips.labels = {g.key: g.label.lower() for g in self.groups}
        chips.refresh(layout=True)

    def set_count(self, shown: int, total: int) -> None:
        chips = self.query_one(Chips)
        chips.count = (shown, total)
        chips.refresh(layout=True)

    def set_facet(self, key: str, value: str | None) -> None:
        if value is None:
            self.facets.pop(key, None)
        else:
            self.facets[key] = value
        chips = self.query_one(Chips)
        chips.facets = dict(self.facets)
        chips.refresh(layout=True)
        self._changed()

    def clear(self) -> None:
        self.facets.clear()
        self.query_one(Chips).facets = {}
        self.query_one(FilterInput).value = ""
        self._changed()

    def choose(self) -> None:
        """Open the facet picker. Does nothing when the list has no facets."""
        if not self.groups:
            return

        def picked(choice: tuple[str, str | None] | None) -> None:
            if choice is not None:
                self.set_facet(*choice)

        self.app.push_screen(FacetPicker(self.groups, self.facets), picked)

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self._changed()

    def _changed(self) -> None:
        self.post_message(self.Changed(self, self.query, self.facets))


class FacetPicker(ModalScreen[tuple[str, str | None] | None]):
    """Pick one value for one facet, or `any` to drop it. `esc` closes without a change."""

    DEFAULT_CSS = """
    FacetPicker {
        align: center middle;
    }
    FacetPicker > OptionList {
        width: 60;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: round $border;
        border-title-color: $foreground;
        background: $surface;
        padding: 0 1;
    }
    """

    BINDINGS = [Binding("escape", "dismiss_none", "Close")]

    def __init__(self, groups: Sequence[FacetGroup], current: Mapping[str, str]) -> None:
        super().__init__()
        self.groups = tuple(groups)
        self.current = dict(current)

    def compose(self) -> ComposeResult:
        options: list[Option | None] = []
        for group in self.groups:
            if options:
                options.append(None)
            options.append(Option(Text(group.label, style="bold"), disabled=True))
            unset = group.key not in self.current
            options.append(Option(self._line(ANY, None, unset), id=f"{group.key}{_SEP}"))
            for facet in group.facets:
                chosen = self.current.get(group.key) == facet.id
                line = self._line(facet.id, facet.count, chosen)
                options.append(Option(line, id=f"{group.key}{_SEP}{facet.id}"))
        picker = OptionList(*options)
        picker.border_title = "Filter by"
        yield picker

    def _line(self, label: str, count: int | None, chosen: bool) -> Text:
        look = look_for(self)
        text = look.mark(PASSED, word=False) if chosen else Text(" ", end="")
        text.append(" ")
        text.append_text(fmt.safe_text(label, single_line=True, style="bold" if chosen else ""))
        if count is not None:
            text.append_text(look.muted(f"  {fmt.count(count)}"))
        return text

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        key, _, value = (event.option.id or "").partition(_SEP)
        self.dismiss((key, value or None))

    def action_dismiss_none(self) -> None:
        self.dismiss(None)
