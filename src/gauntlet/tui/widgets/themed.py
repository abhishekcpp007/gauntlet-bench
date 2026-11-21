"""`Themed`: the base for widgets that draw with the active `Look`."""

from __future__ import annotations

from textual.theme import Theme
from textual.widget import Widget

from ..theme import Look, look_for


class Themed(Widget):
    """A widget that renders with `self.look` and repaints when the theme changes.

    Subclasses build their content in `render()` from `self.look`, so a theme switch needs
    nothing more than a refresh. Override `on_theme_change` to rebuild cached content instead.
    """

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, self._theme_changed)

    def _theme_changed(self, _theme: Theme) -> None:
        self.on_theme_change()

    def on_theme_change(self) -> None:
        self.refresh(layout=True)

    @property
    def look(self) -> Look:
        return look_for(self)
