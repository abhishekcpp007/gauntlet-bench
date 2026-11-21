"""`GauntletApp`: the frame, the destinations, navigation, the palette, help, copy and jobs.

Navigation is a stack per destination (Textual modes): `1` to `4` switch destination and keep
where you were in each, opening a row pushes a detail screen, and `esc` or `backspace` pops it.
Screens move around only through `open_task`, `open_dataset`, `open_run`, `open_episode`,
`open_job` and `open_output`.

Given a `JobRunner`, the app adds `5 Workbench`. It listens to the runner, hands each batch of
events to the screens through `job_events`, counts what's running in the header, says when a job
ends, and swaps in a reloaded source so new task sets and runs show up where you are.
"""

from __future__ import annotations

import asyncio
import contextvars
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import ClassVar, Literal

from rich.text import Text
from textual.app import App
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import reactive
from textual.screen import Screen
from textual.scrollbar import ScrollBar, ScrollBarRender
from textual.signal import Signal
from textual.theme import BUILTIN_THEMES
from textual.worker import Worker, WorkerState

from . import format as fmt
from .jobtypes import FINISHED, JobEvent, JobRecord, JobRunner, Output, Unsubscribe
from .models import DataSource, Overview, SearchHit
from .screens.base import DataScreen, GauntletScreen
from .screens.confirm import ConfirmPrompt
from .screens.dataset import DatasetScreen
from .screens.episode import EpisodeScreen
from .screens.help import HelpScreen
from .screens.job import JobScreen, TextFileScreen
from .screens.overview import OverviewScreen
from .screens.reference import ReferenceScreen
from .screens.run import RunScreen
from .screens.runs import RunsScreen
from .screens.task import TaskScreen
from .screens.tasks import TasksScreen
from .screens.workbench import WorkbenchScreen
from .theme import DEFAULT_THEME, THEMES, Look, look_for, make_look
from .widgets.chrome import Destination
from .widgets.deferred import Deferred
from .widgets.filterbar import FilterBar, FilterInput
from .widgets.grid import DataGrid
from .widgets.jobstatus import ACTIVE
from .widgets.messages import CopyRequested
from .workbench import catalogue
from .workbench.base import ActionForm

EXIT_ERROR = 1
EXIT_USAGE = 2
DEFAULT_DATASETS = Path("datasets")
SEARCH_LIMIT = 40
SEARCH_FALLBACK_SCORE = 0.1
KIND_WIDTH = 8
FLUSH_DELAY = 0.05
RESTORE_TRIES = 20
REFRESHED: tuple[type[DataScreen[object]], ...] = (OverviewScreen, TasksScreen, RunsScreen)
TOAST_SEVERITY: dict[str, Literal["information", "warning", "error"]] = {
    "succeeded": "information",
    "failed": "error",
    "cancelled": "warning",
}

DESTINATIONS: tuple[Destination, ...] = (
    Destination("1", "Overview", "overview"),
    Destination("2", "Tasks", "tasks"),
    Destination("3", "Runs", "runs"),
    Destination("4", "Reference", "reference"),
)
WORKBENCH = Destination("5", "Workbench", "workbench")


@dataclass(frozen=True, slots=True)
class Place:
    """Where the user was on a list screen: each grid's row, which grid had focus, each filter."""

    cursors: tuple[str | None, ...]
    focused: int | None
    filters: tuple[tuple[str, dict[str, str]], ...]


def place_of(screen: Screen) -> Place:
    grids = list(screen.query(DataGrid))
    focused = screen.focused
    at = next(
        (i for i, g in enumerate(grids) if focused is not None and g in focused.ancestors_with_self), None
    )
    bars = tuple((bar.query, dict(bar.facets)) for bar in screen.query(FilterBar))
    return Place(tuple(g.current_key for g in grids), at, bars)


def grids_ready(screen: Screen) -> bool:
    """Whether every grid on the screen has drawn its rows into its table."""
    return all(grid.table.row_count == len(grid.rows) for grid in screen.query(DataGrid))


def restore_place(screen: Screen, place: Place) -> None:
    grids = list(screen.query(DataGrid))
    for grid, key in zip(grids, place.cursors, strict=False):
        if key is not None and key in {grid.row_key(row) for row in grid.rows}:
            grid.table.move_cursor(row=grid.table.get_row_index(key), animate=False)
    if place.focused is not None and place.focused < len(grids):
        grids[place.focused].focus_table()
    for bar, (query, facets) in zip(screen.query(FilterBar), place.filters, strict=False):
        for key, value in facets.items():
            bar.set_facet(key, value)
        if query:
            bar.query_one(FilterInput).value = query


class AsciiScrollBarRender(ScrollBarRender):
    """Scroll bars drawn with spaces only, for --ascii."""

    VERTICAL_BARS: ClassVar[list[str]] = [" "] * len(ScrollBarRender.VERTICAL_BARS)
    HORIZONTAL_BARS: ClassVar[list[str]] = [" "] * len(ScrollBarRender.HORIZONTAL_BARS)


class GauntletCommands(Provider):
    """Command palette results: any task, dataset, run or episode by id, through `DataSource.search`."""

    @property
    def gauntlet(self) -> GauntletApp:
        app = self.app
        assert isinstance(app, GauntletApp)
        return app

    def _display(self, hit: SearchHit) -> Text:
        text = look_for(self.screen).muted(f"{hit.kind:<{KIND_WIDTH}}")
        text.append_text(fmt.safe_text(hit.title, single_line=True))
        return text

    async def search(self, query: str) -> Hits:
        if not query.strip():
            return
        try:
            hits = await asyncio.to_thread(self.gauntlet.source.search, query, limit=SEARCH_LIMIT)
        except Exception as e:  # a failing source shouldn't break the palette
            self.gauntlet.notify(f"Search failed: {e}", severity="error", markup=False)
            return
        matcher = self.matcher(query)
        for hit in hits:
            score = max(matcher.match(hit.title), matcher.match(hit.id), SEARCH_FALLBACK_SCORE)
            yield Hit(
                score,
                self._display(hit),
                partial(self.gauntlet.open_hit, hit),
                text=hit.title,
                help=fmt.one_line(hit.subtitle),
            )

    async def discover(self) -> Hits:
        for destination in self.gauntlet.destinations:
            yield DiscoveryHit(
                f"Go to {destination.label}",
                partial(self.gauntlet.run_action, f"destination('{destination.mode}')"),
                help=f"Key {destination.key}",
            )


class GauntletApp(App[None]):
    """The viewer. Give it any `DataSource`; `run()` below builds the real one."""

    CSS_PATH = "gauntlet.tcss"
    TITLE = "Gauntlet"
    COMMANDS = App.COMMANDS | {GauntletCommands}
    MODES: ClassVar[dict[str, str | Callable[[], Screen]]] = {
        "overview": OverviewScreen,
        "tasks": TasksScreen,
        "runs": RunsScreen,
        "reference": ReferenceScreen,
    }
    DEFAULT_MODE = "overview"

    BINDINGS: ClassVar[list[BindingType]] = [
        *(Binding(d.key, f"destination('{d.mode}')", d.label, show=False) for d in DESTINATIONS),
        Binding("escape,backspace", "back", "Back"),
        Binding("c", "copy", "Copy", show=False),
        Binding("question_mark", "help", "Help"),
        Binding("ctrl+p", "command_palette", "Palette", show=False, priority=True),
        Binding("q", "quit", "Quit"),
    ]

    loaded: reactive[str] = reactive("")

    def __init__(
        self,
        source: DataSource,
        *,
        jobs: JobRunner | None = None,
        reload: Callable[[], DataSource] | None = None,
        actions: Sequence[type[ActionForm]] | None = None,
        ascii: bool = False,
        theme: str | None = None,
    ) -> None:
        super().__init__()
        self.source = source
        self.jobs = jobs
        self.reload_source = reload
        self.actions: tuple[type[ActionForm], ...] = tuple(catalogue() if actions is None else actions)
        self.ascii_mode = ascii
        self.destinations = DESTINATIONS
        self.job_records: dict[str, JobRecord] = {}
        self.job_events: Signal[tuple[JobEvent, ...]] = Signal(self, "job-events")
        self._pending: SimpleQueue[JobEvent] = SimpleQueue()
        self._flush_lock = threading.Lock()
        self._flush_scheduled = False
        self._jobs_loop: asyncio.AbstractEventLoop | None = None
        self._jobs_context: contextvars.Context | None = None
        self._unsubscribe: Unsubscribe | None = None
        self._places: dict[Screen, Place] = {}
        self._stale: set[Screen] = set()
        self._totals = ""
        for gauntlet_theme in THEMES:
            self.register_theme(gauntlet_theme)
        self.theme = theme or DEFAULT_THEME
        self.set_class(ascii, "-ascii")
        self._scrollbar_render = ScrollBar.renderer
        if jobs is not None:
            self.destinations = (*DESTINATIONS, WORKBENCH)
            self.add_mode(WORKBENCH.mode, partial(WorkbenchScreen, self.actions))
            self.bind(
                WORKBENCH.key, f"destination('{WORKBENCH.mode}')", description=WORKBENCH.label, show=False
            )

    def on_mount(self) -> None:
        if self.ascii_mode:
            ScrollBar.renderer = AsciiScrollBarRender
        self.run_worker(self.source.overview, thread=True, name="loaded", exit_on_error=False)
        if self.jobs is not None:
            self._jobs_loop = asyncio.get_running_loop()
            self._jobs_context = contextvars.copy_context()
            self._unsubscribe = self.jobs.subscribe(self._job_listener)
            self.run_worker(self.jobs.jobs, thread=True, name="jobs", exit_on_error=False)

    def on_unmount(self) -> None:
        ScrollBar.renderer = self._scrollbar_render
        self._jobs_loop = None
        if self._unsubscribe is not None:
            self._unsubscribe()
        if self.jobs is not None:
            self.jobs.close()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.ERROR and event.worker.name == "reload" and event.worker.error:
            self.notify(f"Couldn't reload the data: {event.worker.error}", severity="error", markup=False)
        if event.state != WorkerState.SUCCESS:
            return
        result = event.worker.result
        if event.worker.name == "loaded" and isinstance(result, Overview):
            totals = result.totals
            dot = f" {self.look.glyphs.dot} "
            self._totals = dot.join([fmt.plural(totals.tasks, "task"), fmt.plural(totals.runs, "run")])
            self.show_loaded()
        elif event.worker.name == "jobs" and isinstance(result, tuple):
            for record in result:
                if isinstance(record, JobRecord):
                    self.job_records.setdefault(record.id, record)
            self.show_loaded()
            self.job_events.publish(())
        elif event.worker.name == "reload" and result is not None:
            self.source_reloaded(result)

    def show_loaded(self) -> None:
        """The right side of the header: jobs in flight, if any, then what's loaded."""
        dot = f" {self.look.glyphs.dot} "
        records = self.job_records.values()
        running = sum(r.state == "running" for r in records)
        queued = sum(r.state == "queued" for r in records)
        jobs = []
        if running:
            jobs.append(f"{fmt.plural(running, 'job')} running")
        if queued:
            jobs.append(f"{queued} queued" if running else f"{fmt.plural(queued, 'job')} queued")
        self.loaded = dot.join([*jobs, *([self._totals] if self._totals else [])])

    def _job_listener(self, event: JobEvent) -> None:
        """Called from the runner's threads: queue the event and wake the UI thread once."""
        self._pending.put(event)
        with self._flush_lock:
            if self._flush_scheduled:
                return
            self._flush_scheduled = True
        loop = self._jobs_loop
        try:
            if loop is None:
                raise RuntimeError("the app isn't running")
            loop.call_soon_threadsafe(self._schedule_flush, context=self._jobs_context)
        except RuntimeError:
            with self._flush_lock:
                self._flush_scheduled = False

    def _schedule_flush(self) -> None:
        self.set_timer(FLUSH_DELAY, self.flush_jobs)

    def flush_jobs(self) -> None:
        """Hand every queued job event to the screens now."""
        with self._flush_lock:
            self._flush_scheduled = False
        events: list[JobEvent] = []
        while True:
            try:
                events.append(self._pending.get_nowait())
            except Empty:
                break
        if not events:
            return
        ended: list[JobRecord] = []
        for event in events:
            before = self.job_records.get(event.record.id)
            self.job_records[event.record.id] = event.record
            done = event.record.state in FINISHED
            if event.kind == "state" and done and (before is None or before.state not in FINISHED):
                ended.append(event.record)
        self.show_loaded()
        self.job_events.publish(tuple(events))
        for record in ended:
            word = record.state
            self.notify(
                f"{record.spec.title} {word}.",
                title="Job finished",
                severity=TOAST_SEVERITY[word],
                markup=False,
            )
        if ended and self.reload_source is not None:
            self.run_worker(
                self.reload_source,
                thread=True,
                name="reload",
                group="reload",
                exclusive=True,
                exit_on_error=False,
            )

    def restore_when_ready(self, screen: Screen, place: Place, tries: int) -> None:
        if not screen.is_mounted:
            return
        if grids_ready(screen) or not tries:
            restore_place(screen, place)
        else:
            self.call_after_refresh(self.restore_when_ready, screen, place, tries - 1)

    def remember_job(self, record: JobRecord) -> None:
        """A job this app just submitted, so the header and the list know it before its first event."""
        self.job_records.setdefault(record.id, record)
        self.show_loaded()

    def all_screens(self) -> Iterator[Screen]:
        for stack in self._screen_stacks.values():
            yield from stack

    def source_reloaded(self, source: DataSource) -> None:
        """Use the fresh data and reload the list screens, keeping each one's place."""
        self.source = source
        self.run_worker(self.source.overview, thread=True, name="loaded", exit_on_error=False)
        self._stale = {s for s in self.all_screens() if isinstance(s, REFRESHED) and s.is_mounted}
        self.refresh_stale()

    def refresh_stale(self) -> None:
        """Reload the screen in front if the data changed since it loaded, keeping its place."""
        screen = self.screen
        if screen in self._stale and isinstance(screen, DataScreen):
            self._stale.discard(screen)
            self._places[screen] = place_of(screen)
            screen.reload()

    def on_deferred_ready(self, event: Deferred.Ready) -> None:
        screen = event.deferred.screen
        if event.deferred.id == "body" and screen in self._places:
            self.call_after_refresh(self.restore_when_ready, screen, self._places.pop(screen), RESTORE_TRIES)

    @property
    def look(self) -> Look:
        return make_look(self.theme_variables, ascii=self.ascii_mode)

    def watch_loaded(self) -> None:
        for screen in self.screen_stack:
            if isinstance(screen, GauntletScreen) and screen.is_mounted:
                screen.refresh_chrome()

    def get_key_display(self, binding: Binding) -> str:
        display = super().get_key_display(binding)
        return binding.key if self.ascii_mode and not display.isascii() else display

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action == "back":
            return len(self.screen_stack) > 1
        return True

    def open_task(self, instance_id: str) -> None:
        self.push_screen(TaskScreen(instance_id))

    def open_dataset(self, dataset_id: str) -> None:
        self.push_screen(DatasetScreen(dataset_id))

    def open_run(self, run_id: str) -> None:
        self.push_screen(RunScreen(run_id))

    def open_episode(self, run_id: str, episode_id: str) -> None:
        self.push_screen(EpisodeScreen(run_id, episode_id))

    def open_job(self, job_id: str) -> None:
        self.push_screen(JobScreen(job_id))

    def open_text(self, path: str, title: str) -> None:
        self.push_screen(TextFileScreen(path, title))

    def open_output(self, output: Output) -> None:
        """Open what a job made: its task set, its run, or the file itself as text."""
        if output.kind in ("run", "tasks"):
            self.run_worker(
                partial(self.find_output, output), thread=True, group="output", exit_on_error=False
            )
        else:
            self.open_text(output.path, output.label)

    def find_output(self, output: Output) -> None:
        path = Path(output.path)
        if output.kind == "run":
            resolved = path.resolve()
            for run in self.source.runs():
                if run.id == path.name or (run.path is not None and Path(run.path).resolve() == resolved):
                    self.call_from_thread(self.open_run, run.id)
                    return
        else:
            name = path.parent.name if path.suffix else path.name
            for dataset in self.source.datasets():
                if dataset.id == name:
                    self.call_from_thread(self.open_dataset, dataset.id)
                    return
        message = f"{output.label} isn't loaded yet. It's at {output.path}."
        self.call_from_thread(self.notify, message, severity="warning", markup=False)

    def open_hit(self, hit: SearchHit) -> None:
        """Go to a command palette result."""
        if hit.kind == "task":
            self.open_task(hit.id)
        elif hit.kind == "dataset":
            self.open_dataset(hit.id)
        elif hit.kind == "run":
            self.open_run(hit.id)
        elif hit.kind == "episode" and hit.run_id is not None:
            self.open_episode(hit.run_id, hit.id)

    def copy(self, text: str, what: str = "id") -> None:
        self.copy_to_clipboard(text)
        self.notify(f"Copied {what}: {text}", title="Copied", markup=False)

    def on_copy_requested(self, message: CopyRequested) -> None:
        self.copy(message.text, message.what)

    async def action_destination(self, mode: str) -> None:
        await self.switch_mode(mode)
        self.refresh_stale()

    def action_back(self) -> None:
        if len(self.screen_stack) > 1 and not isinstance(self.screen, HelpScreen):
            self.pop_screen()
            self.call_after_refresh(self.refresh_stale)

    def action_copy(self) -> None:
        target = self.screen.copy_target() if isinstance(self.screen, GauntletScreen) else None
        if target is None:
            self.notify("Nothing to copy here.", markup=False)
            return
        self.copy(*target)

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen(self.screen))

    async def action_quit(self) -> None:
        active = [r for r in self.job_records.values() if r.state in ACTIVE]
        if not active:
            self.exit()
            return
        if isinstance(self.screen, ConfirmPrompt):
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self.exit()

        question = f"{fmt.plural(len(active), 'job')} still running or queued. Quit anyway?"
        detail = "Quitting stops them. What they wrote so far stays in the workspace."
        self.push_screen(ConfirmPrompt(question, detail, yes="Quit", no="Stay"), answered)


def load_source(datasets: Path | None, runs: Sequence[Path]) -> DataSource:
    """The real data. Kept in one place so the store's constructor can change in one line."""
    from gauntlet.tui.store import Store

    return Store.load(datasets, list(runs))


def load_workbench(
    datasets: Path | None, runs: Sequence[Path], workspace: Path
) -> tuple[DataSource, JobRunner, Callable[[], DataSource]]:
    """The real data with the workspace's task sets and runs, the real runner, and how to reload.
    Kept in one place so a change to either constructor is a one-line fix."""
    from gauntlet.tui.jobs import SubprocessJobRunner
    from gauntlet.tui.store import Store
    from gauntlet.tui.workspace import Workspace

    def reload() -> DataSource:
        return Store.load(datasets, list(runs), workspace=workspace)

    return reload(), SubprocessJobRunner(Workspace(workspace)), reload


def run(
    datasets: str | Path | None = None,
    runs: Sequence[str | Path] | None = None,
    *,
    ascii: bool = False,
    theme: str | None = None,
    workspace: str | Path | None = None,
) -> int:
    """`gauntlet tui`: load what was asked for, then start the viewer. Returns the exit code.

    With a `workspace`, the Workbench is on and its jobs write there; without one it's the viewer."""
    if theme is not None and theme not in {t.name for t in THEMES} | set(BUILTIN_THEMES):
        print(f"error: no theme called {theme}. Try {' or '.join(t.name for t in THEMES)}.")
        return EXIT_USAGE
    root = Path(datasets) if datasets else (DEFAULT_DATASETS if DEFAULT_DATASETS.is_dir() else None)
    run_dirs = [Path(r) for r in runs or ()]
    missing = [str(p) for p in [*([root] if root else []), *run_dirs] if not p.is_dir()]
    if workspace is not None and Path(workspace).exists() and not Path(workspace).is_dir():
        missing.append(str(workspace))
    if missing:
        print(f"error: not a folder: {', '.join(missing)}")
        return EXIT_USAGE
    jobs: JobRunner | None = None
    reload: Callable[[], DataSource] | None = None
    try:
        if workspace is None:
            source = load_source(root, run_dirs)
        else:
            source, jobs, reload = load_workbench(root, run_dirs, Path(workspace))
    except Exception as e:  # a broken run folder gets one line, not a traceback
        print(f"error: couldn't load the data: {type(e).__name__}: {e}")
        return EXIT_ERROR
    GauntletApp(source, jobs=jobs, reload=reload, ascii=ascii, theme=theme).run()
    return 0
