"""`GauntletScreen` and `DataScreen`: the frame and the load pattern every screen shares."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, ClassVar, Generic, TypeVar, cast

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.events import Resize
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Footer, TabbedContent

from ..models import DataSource
from ..widgets.chrome import NavBar, TopBar
from ..widgets.deferred import Deferred
from ..widgets.filterbar import FilterBar

if TYPE_CHECKING:
    from ..app import GauntletApp

T = TypeVar("T")

ROOMY_FOOTER = 100


class GauntletScreen(Screen[None]):
    """The header, the destination bar, a body from `compose_body`, and the footer.

    Set `crumb` to the short label this screen adds to the breadcrumbs. Override `copy_target`
    to say what `c` copies when no focused widget copies something itself.
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("tab", "app.focus_next", "Next pane", show=False),
        Binding("shift+tab", "app.focus_previous", "Prev pane", show=False),
        Binding("ctrl+c,super+c", "screen.copy_text", "Copy selection", show=False),
        Binding("slash", "filter", "Filter"),
        Binding("f", "facets", "Facets"),
        Binding("right_square_bracket,l", "tab(1)", "Tab"),
        Binding("left_square_bracket,h", "tab(-1)", "Prev tab", show=False),
    ]

    crumb: str = ""
    pending_tab_steps: int = 0

    @property
    def gauntlet(self) -> GauntletApp:
        return cast("GauntletApp", self.app)

    @property
    def source(self) -> DataSource:
        return self.gauntlet.source

    def compose(self) -> ComposeResult:
        yield TopBar()
        yield NavBar(self.gauntlet.destinations, self.gauntlet.current_mode)
        yield from self.compose_body()
        yield Footer()

    def compose_body(self) -> ComposeResult:
        yield from ()

    def copy_target(self) -> tuple[str, str] | None:
        """`(text, what)` for `c`, or None when this screen has nothing to copy."""
        return None

    def crumbs(self) -> tuple[str, ...]:
        """This screen's breadcrumbs: every screen below it in this destination, then itself."""
        stack = self.app.screen_stack
        upto = stack[: stack.index(self) + 1] if self in stack else [self]
        return tuple(s.crumb for s in upto if isinstance(s, GauntletScreen) and s.crumb)

    def refresh_chrome(self) -> None:
        self.query_one(TopBar).show(self.crumbs(), self.gauntlet.loaded)

    def on_mount(self) -> None:
        self.refresh_chrome()

    def on_screen_resume(self) -> None:
        self.refresh_chrome()

    def on_resize(self, event: Resize) -> None:
        roomy = event.size.width >= ROOMY_FOOTER
        for footer in self.query(Footer):
            if footer.show_command_palette != roomy:
                footer.show_command_palette = roomy
                footer.refresh(recompose=True)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "filter":
            return bool(self.visible_filter_bars())
        if action == "facets":
            return any(bar.groups for bar in self.visible_filter_bars())
        if action == "tab":
            return bool(self.query(TabbedContent)) or self.loading
        return True

    def visible_filter_bars(self) -> list[FilterBar]:
        """Filter bars that are showing: not in a hidden tab, not hidden themselves."""
        return [bar for bar in self.query(FilterBar) if all(node.display for node in bar.ancestors_with_self)]

    def on_tabbed_content_tab_activated(self) -> None:
        self.refresh_bindings()

    def action_filter(self) -> None:
        for bar in self.visible_filter_bars():
            bar.focus_input()
            return

    def action_facets(self) -> None:
        for bar in self.visible_filter_bars():
            if bar.groups:
                bar.choose()
                return

    @property
    def loading(self) -> bool:
        """True while the screen's body is still on its way."""
        return False

    def action_tab(self, step: int) -> None:
        if not self.query(TabbedContent):
            self.pending_tab_steps += step
            return
        tabs = self.query(TabbedContent).first()
        panes = [pane.id for pane in tabs.query("TabPane") if pane.id and not pane.disabled]
        if not panes:
            return
        current = panes.index(tabs.active) if tabs.active in panes else 0
        tabs.active = panes[(current + step) % len(panes)]


class DataScreen(GauntletScreen, Generic[T]):
    """A screen whose body is loaded once, off the UI thread.

    Implement `fetch` (runs in a worker thread: call `self.source` there, nothing else) and
    `build` (runs on the UI thread with the result: yield the widgets to show). Until `fetch`
    returns the body shows `Loading`, and if it raises the body shows `ErrorState` instead.
    """

    what: ClassVar[str] = "data"

    def compose_body(self) -> ComposeResult:
        yield Deferred(self.fetch, self.build, what=self.what, lazy=False, id="body")

    def fetch(self) -> T:
        raise NotImplementedError

    def build(self, data: T) -> Iterable[Widget]:
        raise NotImplementedError

    def reload(self) -> None:
        self.query_one("#body", Deferred).load()

    @property
    def loading(self) -> bool:
        return any(not body.ready for body in self.query("#body").results(Deferred))

    def on_deferred_ready(self, event: Deferred.Ready) -> None:
        """Tab keys pressed while the body loaded are applied once the tabs exist."""
        if event.deferred.id != "body":
            return
        self.refresh_bindings()
        steps, self.pending_tab_steps = self.pending_tab_steps, 0
        if steps and self.query(TabbedContent):
            self.call_after_refresh(self.action_tab, steps)
