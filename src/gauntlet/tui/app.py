"""`GauntletApp`: the frame, the four destinations, navigation, the palette, help and copy.

Navigation is a stack per destination (Textual modes): `1` to `4` switch destination and keep
where you were in each, opening a row pushes a detail screen, and `esc` or `backspace` pops it.
Screens move around only through `open_task`, `open_dataset`, `open_run` and `open_episode`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from functools import partial
from pathlib import Path
from typing import ClassVar

from rich.text import Text
from textual.app import App
from textual.binding import Binding, BindingType
from textual.command import DiscoveryHit, Hit, Hits, Provider
from textual.reactive import reactive
from textual.screen import Screen
from textual.scrollbar import ScrollBar, ScrollBarRender
from textual.theme import BUILTIN_THEMES
from textual.worker import Worker, WorkerState

from . import format as fmt
from .models import DataSource, Overview, SearchHit
from .screens.base import GauntletScreen
from .screens.dataset import DatasetScreen
from .screens.episode import EpisodeScreen
from .screens.help import HelpScreen
from .screens.overview import OverviewScreen
from .screens.reference import ReferenceScreen
from .screens.run import RunScreen
from .screens.runs import RunsScreen
from .screens.task import TaskScreen
from .screens.tasks import TasksScreen
from .theme import DEFAULT_THEME, THEMES, Look, look_for, make_look
from .widgets.chrome import Destination
from .widgets.messages import CopyRequested

EXIT_ERROR = 1
EXIT_USAGE = 2
DEFAULT_DATASETS = Path("datasets")
SEARCH_LIMIT = 40
SEARCH_FALLBACK_SCORE = 0.1
KIND_WIDTH = 8

DESTINATIONS: tuple[Destination, ...] = (
    Destination("1", "Overview", "overview"),
    Destination("2", "Tasks", "tasks"),
    Destination("3", "Runs", "runs"),
    Destination("4", "Reference", "reference"),
)


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
        for destination in DESTINATIONS:
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

    def __init__(self, source: DataSource, *, ascii: bool = False, theme: str | None = None) -> None:
        super().__init__()
        self.source = source
        self.ascii_mode = ascii
        self.destinations = DESTINATIONS
        for gauntlet_theme in THEMES:
            self.register_theme(gauntlet_theme)
        self.theme = theme or DEFAULT_THEME
        self.set_class(ascii, "-ascii")
        self._scrollbar_render = ScrollBar.renderer

    def on_mount(self) -> None:
        if self.ascii_mode:
            ScrollBar.renderer = AsciiScrollBarRender
        self.run_worker(self.source.overview, thread=True, name="loaded", exit_on_error=False)

    def on_unmount(self) -> None:
        ScrollBar.renderer = self._scrollbar_render

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.name == "loaded" and event.state == WorkerState.SUCCESS:
            overview = event.worker.result
            if isinstance(overview, Overview):
                totals = overview.totals
                dot = f" {self.look.glyphs.dot} "
                self.loaded = dot.join([fmt.plural(totals.tasks, "task"), fmt.plural(totals.runs, "run")])

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

    def action_back(self) -> None:
        if len(self.screen_stack) > 1 and not isinstance(self.screen, HelpScreen):
            self.pop_screen()

    def action_copy(self) -> None:
        target = self.screen.copy_target() if isinstance(self.screen, GauntletScreen) else None
        if target is None:
            self.notify("Nothing to copy here.", markup=False)
            return
        self.copy(*target)

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen(self.screen))


def load_source(datasets: Path | None, runs: Sequence[Path]) -> DataSource:
    """The real data. Kept in one place so the store's constructor can change in one line."""
    from gauntlet.tui.store import Store

    return Store.load(datasets, list(runs))


def run(
    datasets: str | Path | None = None,
    runs: Sequence[str | Path] | None = None,
    *,
    ascii: bool = False,
    theme: str | None = None,
) -> int:
    """`gauntlet tui`: load what was asked for, then start the viewer. Returns the exit code."""
    if theme is not None and theme not in {t.name for t in THEMES} | set(BUILTIN_THEMES):
        print(f"error: no theme called {theme}. Try {' or '.join(t.name for t in THEMES)}.")
        return EXIT_USAGE
    root = Path(datasets) if datasets else (DEFAULT_DATASETS if DEFAULT_DATASETS.is_dir() else None)
    run_dirs = [Path(r) for r in runs or ()]
    missing = [str(p) for p in [*([root] if root else []), *run_dirs] if not p.is_dir()]
    if missing:
        print(f"error: not a folder: {', '.join(missing)}")
        return EXIT_USAGE
    try:
        source = load_source(root, run_dirs)
    except Exception as e:  # a broken run folder gets one line, not a traceback
        print(f"error: couldn't load the data: {type(e).__name__}: {e}")
        return EXIT_ERROR
    GauntletApp(source, ascii=ascii, theme=theme).run()
    return 0
