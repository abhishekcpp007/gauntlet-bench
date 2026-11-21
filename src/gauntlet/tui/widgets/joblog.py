"""`JobLog`: a job's output as it arrives, safe to point at anything a repo or an agent prints.

    log = JobLog(log_path="gauntlet-work/jobs/7/log.txt")
    log.write([("collecting PRs", "out"), ("rate limited", "err")])

It keeps the last `window` lines and says when earlier ones are only in the log file, so 50,000
lines cost no more than a few thousand. It follows new output until you scroll up or press `f`.
`/` searches and `n`/`N` move between matches. Every line is literal: markup isn't read, and
control characters and escape sequences show in caret form (`^[`). Lines from stderr carry a dim
mark in the gutter, so they stand out without colour.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.geometry import Size
from textual.message import Message
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Input

from .. import format as fmt
from ..jobtypes import Stream
from ..theme import look_for, solid_color

LOG_WINDOW = 10_000
ERR_MARK = "▌"
ERR_MARK_ASCII = "!"
GUTTER = 2
NOT_FOUND = -1


@dataclass(frozen=True, slots=True)
class LogLine:
    text: str
    err: bool = False


def split_lines(text: str) -> list[str]:
    """One chunk of output as the lines a terminal would show: a carriage return starts the line
    over, so a progress bar leaves only its last state."""
    parts = text.rstrip("\r\n").split("\n")
    return [part.rstrip("\r").rsplit("\r", 1)[-1] for part in parts]


class LogLines(ScrollView, can_focus=True):
    """The scrolling lines. Renders only what's on screen."""

    HELP_GROUP = "Log"
    BINDINGS = [
        Binding("down,j", "down", "Down", show=False),
        Binding("up,k", "up", "Up", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
        Binding("g,home", "top", "Top", show=False),
        Binding("G,end", "bottom", "Bottom", show=False),
        Binding("left", "sideways(-1)", "Left", show=False),
        Binding("right", "sideways(1)", "Right", show=False),
    ]

    DEFAULT_CSS = """
    LogLines {
        height: 1fr;
        background: $surface;
    }
    """

    follow: reactive[bool] = reactive(True)

    class Followed(Message):
        """Following switched on or off."""

        def __init__(self, follow: bool) -> None:
            super().__init__()
            self.follow = follow

    def __init__(self, *, window: int = LOG_WINDOW, log_path: str = "") -> None:
        super().__init__()
        self.lines: deque[LogLine] = deque(maxlen=window)
        self.window = window
        self.log_path = log_path
        self.truncated = False
        self.total = 0
        self.widest = 0
        self.needle = ""
        self.match = NOT_FOUND

    @property
    def banner(self) -> int:
        return 1 if self.truncated else 0

    def write(self, lines: Iterable[tuple[str, Stream | None]], *, earlier: bool = False) -> None:
        """Add lines at the end. `earlier` says there were lines before these that aren't shown."""
        if earlier:
            self.truncated = True
        for text, stream in lines:
            for part in split_lines(text):
                if len(self.lines) == self.window:
                    self.truncated = True
                self.lines.append(LogLine(part, stream == "err"))
                self.total += 1
                self.widest = max(self.widest, len(part))
        self._resize()
        if self.follow:
            self.call_after_refresh(self.to_end)

    def to_end(self) -> None:
        if self.follow:
            self.scroll_to(y=self.max_scroll_y, animate=False, immediate=True)

    def clear(self) -> None:
        self.lines.clear()
        self.truncated = False
        self.total = 0
        self.widest = 0
        self._resize()

    def _resize(self) -> None:
        self.virtual_size = Size(self.widest + GUTTER, len(self.lines) + self.banner)
        self.refresh()

    def watch_follow(self, follow: bool) -> None:
        if follow:
            self.call_after_refresh(self.to_end)
        self.post_message(self.Followed(follow))

    def action_down(self) -> None:
        self.scroll_relative(y=1, animate=False)

    def action_up(self) -> None:
        self.follow = False
        self.scroll_relative(y=-1, animate=False)

    def action_page(self, direction: int) -> None:
        if direction < 0:
            self.follow = False
        self.scroll_relative(y=direction * self.scrollable_content_region.height, animate=False)

    def action_top(self) -> None:
        self.follow = False
        self.scroll_home(animate=False)

    def action_bottom(self) -> None:
        self.follow = True

    def action_sideways(self, direction: int) -> None:
        self.scroll_relative(x=direction * GUTTER * GUTTER, animate=False)

    def find(self, needle: str, *, step: int = 1, start: int | None = None) -> bool:
        """Scroll to the next line holding `needle` (any case), going `step` from `start`."""
        self.needle = needle
        if not needle or not self.lines:
            self.match = NOT_FOUND
            self.refresh()
            return False
        lowered = needle.casefold()
        count = len(self.lines)
        origin = (self.match if self.match != NOT_FOUND else int(self.scroll_y)) if start is None else start
        for offset in range(count):
            index = (origin + step * offset) % count
            if lowered in self.lines[index].text.casefold():
                self.match = index
                self.follow = False
                row = index + self.banner
                self.scroll_to(y=max(row - self.scrollable_content_region.height // 2, 0), animate=False)
                self.refresh()
                return True
        self.match = NOT_FOUND
        self.refresh()
        return False

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        row = scroll_y + y
        width = self.scrollable_content_region.width
        look = look_for(self)
        base = self.rich_style
        if self.truncated and row == 0:
            text = look.muted(f"Earlier lines are only in the log file: {self.log_path or 'the job log'}")
            text.stylize("italic")
        else:
            index = row - self.banner
            if not 0 <= index < len(self.lines):
                return Strip.blank(width, base)
            line = self.lines[index]
            mark = (ERR_MARK_ASCII if look.ascii else ERR_MARK) if line.err else " "
            text = Text(end="", no_wrap=True)
            text.append(f"{mark} ", style=look.style("muted"))
            text.append_text(fmt.safe_text(line.text))
            if self.needle:
                highlight = Style(
                    bgcolor=solid_color(self.app.theme_variables, "block-cursor-background"), bold=True
                )
                text.highlight_words([self.needle], style=highlight, case_sensitive=False)
                if index == self.match:
                    text.stylize(Style(underline=True), GUTTER)
        segments = [
            Segment(s.text, base + s.style if s.style else base) for s in text.render(self.app.console)
        ]
        strip = Strip(segments).crop(scroll_x, scroll_x + width)
        return strip.extend_cell_length(width, base)


class LogSearch(Input):
    """The search box under the log. `enter` keeps the match, `esc` closes it."""

    HELP_GROUP = "Log search"
    BINDINGS = [Binding("escape", "close", "Close search")]

    def action_close(self) -> None:
        log = self.parent
        if isinstance(log, JobLog):
            log.close_search()


class JobLog(Vertical):
    """The lines and their search box. See the module docstring."""

    HELP_GROUP = "Log"
    BINDINGS = [
        Binding("n", "next_match(1)", "Next match", show=False),
        Binding("N", "next_match(-1)", "Prev match", show=False),
    ]

    DEFAULT_CSS = """
    JobLog {
        height: 1fr;
    }
    JobLog > LogSearch {
        display: none;
        height: 1;
        border: none;
        padding: 0 1;
        background: $boost;
    }
    JobLog.-searching > LogSearch {
        display: block;
    }
    """

    def __init__(
        self,
        *,
        window: int = LOG_WINDOW,
        log_path: str = "",
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.window = window
        self.log_path = log_path
        self.search_from = 0

    def compose(self) -> ComposeResult:
        yield LogLines(window=self.window, log_path=self.log_path)
        yield LogSearch(placeholder="search the log, enter keeps the match", compact=True)

    @property
    def lines(self) -> LogLines:
        return self.query_one(LogLines)

    @property
    def follow(self) -> bool:
        return self.lines.follow

    def write(self, lines: Iterable[tuple[str, Stream | None]], *, earlier: bool = False) -> None:
        self.lines.write(lines, earlier=earlier)

    def set_log_path(self, path: str) -> None:
        self.log_path = path
        self.lines.log_path = path
        self.lines.refresh()

    def toggle_follow(self) -> None:
        self.lines.follow = not self.lines.follow

    def open_search(self) -> None:
        lines = self.lines
        self.search_from = max(int(lines.scroll_y) - lines.banner, 0)
        self.add_class("-searching")
        self.query_one(LogSearch).focus()

    def close_search(self) -> None:
        self.remove_class("-searching")
        search = self.query_one(LogSearch)
        search.value = ""
        self.lines.find("")
        self.lines.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        self.lines.match = NOT_FOUND
        self.lines.find(event.value, start=self.search_from)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.remove_class("-searching")
        self.lines.focus()

    def action_next_match(self, step: int) -> None:
        lines = self.lines
        if lines.needle:
            start = lines.match + step if lines.match != NOT_FOUND else None
            lines.find(lines.needle, step=step, start=start)
