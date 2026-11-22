"""Widgets a form adds to its own `FormView`, beyond its fields, and `FormNote`, a line of text.

The form framework draws a form's fields and nothing else, and has no hook that hands a form its
view. The one place a form's own code runs inside the view is a field's `options` loader, which
runs in a worker of that field's row. `mount_from_loader`, called from such a loader, finds the
row through Textual's current worker and mounts the widgets a form asks for into its view, once.
A form that needs a note above its fields, a button between them, or to hear when a job ends uses
this. Outside a form's loader it does nothing, so a form still works without its extras.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from weakref import WeakSet

from rich.console import RenderableType
from textual.widget import Widget
from textual.worker import NoActiveWorker, get_current_worker

from .form import FieldRow, FormBanner, FormView
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


def mount_from_loader(extras: Extras) -> None:
    """Mount `extras(view)` into the form view whose field loader is running now. Call it from a
    field's `options` loader; anywhere else, or a second time for the same view, it does nothing."""
    try:
        worker = get_current_worker()
    except NoActiveWorker:
        return
    row = worker.node
    if not isinstance(row, FieldRow) or not worker.is_running:
        return
    row.app.call_from_thread(add_extras, row.form, extras)


def add_extras(view: FormView, extras: Extras) -> None:
    """Mount each widget after its field, or under the banner, once the view is mounted. Only
    once for a view."""
    if view in _EXTENDED:
        return
    if not view.is_mounted:
        view.call_after_refresh(add_extras, view, extras)
        return
    _EXTENDED.add(view)
    for widget, after in extras(view):
        if after is None:
            view.mount(widget, after=view.query_one(FormBanner))
        else:
            view.mount(widget, after=view.row(after))
