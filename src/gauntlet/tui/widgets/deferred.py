"""`Deferred`: a pane that loads its own data in a thread and then builds its content.

    Deferred(lambda: source.trajectory(run_id, episode_id), self.build_timeline, what="trajectory")

It shows `Loading` until `fetch` returns, then mounts what `build` yields and, if nothing on the
screen has focus yet, focuses the first thing in it you can move around in. If `fetch` raises, it
shows an `ErrorState` with one plain line instead, and the app carries on. With `lazy=True`
(the default) nothing loads until the pane is first shown, so a tab that's never opened costs
nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Generic, TypeVar, cast

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Input
from textual.worker import Worker, WorkerState

from .states import ErrorState, Loading, describe_error

T = TypeVar("T")


class Deferred(Vertical, Generic[T]):
    DEFAULT_CSS = """
    Deferred {
        height: 1fr;
    }
    """

    def __init__(
        self,
        fetch: Callable[[], T],
        build: Callable[[T], Iterable[Widget]],
        *,
        what: str,
        lazy: bool = True,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.fetch = fetch
        self.build = build
        self.what = what
        self.lazy = lazy
        self.state: WorkerState | None = None
        self._worker: Worker[T] | None = None

    def compose(self) -> ComposeResult:
        yield Loading(self.what)

    def on_mount(self) -> None:
        if not self.lazy:
            self.load()

    def on_show(self) -> None:
        if self._worker is None:
            self.load()

    def load(self) -> None:
        """Start the load, or start it again to reload."""
        if self.state is not None:
            self.remove_children()
            self.mount(Loading(self.what))
        self.state = WorkerState.PENDING
        self._worker = self.run_worker(self.fetch, thread=True, exclusive=True, exit_on_error=False)

    async def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        event.stop()
        self.state = event.state
        if event.state == WorkerState.SUCCESS:
            try:
                content = list(self.build(cast(T, event.worker.result)))
            except Exception as error:  # a record the screen can't draw still mustn't take the app down
                content = [self._failed(error)]
        elif event.state == WorkerState.ERROR and event.worker.error is not None:
            content = [self._failed(event.worker.error)]
        else:
            return
        await self.remove_children()
        await self.mount_all(content)
        if self.screen.focused is None:
            for widget in self.query("*"):
                if widget.focusable and not isinstance(widget, Input):
                    widget.focus()
                    break

    def _failed(self, error: BaseException) -> ErrorState:
        return ErrorState(f"Couldn't load {self.what}", describe_error(error))
