"""`Timeline`: an episode's trajectory, one row per sandbox step, each one expandable in place.

A row shows the step's index, kind, command or path (cut to one line), exit code, duration and
its marks: timed out, truncated, and flagged by Cheat Catcher (the rule ids, in the cheating
colour). `enter` or `space` opens a step to show its full command, stdout, stderr and file
content. Agents wrote all of that, so it's drawn literally: markup isn't read and control
characters show in caret form. Long output stops after `MAX_SHOWN_LINES` until `m` shows the
rest. `n` and `N` jump between flagged steps. Rows are drawn on demand, so 400 steps scroll as
fast as 4.

Steps keep the sandbox's own indices, which are the numbers Cheat Catcher's findings use. The
first few steps are the harness setting the sandbox up, but nothing in the record marks where
the agent's own steps start, so they're shown like every other step.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from rich.cells import cell_len, chop_cells
from rich.console import RenderableType
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.events import Click, Resize
from textual.geometry import Size
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .. import format as fmt
from ..models import Trajectory, TrajectoryHeader, TrajectoryStep
from ..theme import FAILED, SUMMARY_ONLY, VERDICTS, WARNING, Look, Mark, look_for, solid_color
from .states import Empty, EmptyState
from .themed import Themed

MAX_SHOWN_LINES = 30
KIND_WIDTH = 11
EXIT_WIDTH = 5
TIME_WIDTH = 8
GAP = 2
INDENT = 4
LABEL_WIDTH = 9
MIN_COMMAND_WIDTH = 12
MARKS_SHARE = 2
ROOMY_WIDTH = 90
HEADER_ROWS = 1
FIXED_GAPS = 3
MARK_PREFIX = 2
GUTTER_SIDES = 2

FLAGGED = replace(VERDICTS["cheating"], word="flagged")
TIMED_OUT = replace(WARNING, word="timed out")
TRUNCATED = replace(SUMMARY_ONLY, word="truncated")
NO_STEPS = Empty("The trajectory has no steps.", "The sandbox recorded a header but no actions.")

LineKind = Literal["row", "text", "label", "more", "note"]


@dataclass(frozen=True, slots=True)
class Line:
    """One display line: a step's row, or a line of its expanded detail."""

    kind: LineKind
    step: int
    text: str = ""
    label: str = ""


@dataclass(frozen=True, slots=True)
class Layout:
    index: int
    command: int
    marks: int
    roomy: bool


def _cpus(cpus: float) -> str:
    shown = f"{cpus:g}"
    return f"{shown} CPU" if cpus == 1 else f"{shown} CPUs"


def step_target(step: TrajectoryStep) -> str:
    """What the step acted on, on one line: the command, or the path for a file step."""
    if step.command:
        return fmt.one_line(step.command)
    return step.path or ""


def step_marks(step: TrajectoryStep) -> list[tuple[Mark, str]]:
    """The marks a row carries, each with the extra words after the mark's own."""
    marks: list[tuple[Mark, str]] = []
    if step.flagged:
        marks.append((FLAGGED, ", ".join(step.flagged)))
    if step.timed_out:
        marks.append((TIMED_OUT, ""))
    if step.truncated:
        marks.append((TRUNCATED, ""))
    return marks


class TimelineHeader(Themed):
    """The sandbox the steps ran in: image, network, memory and CPUs, then any load warnings."""

    DEFAULT_CSS = """
    TimelineHeader {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, header: TrajectoryHeader | None, warnings: tuple[str, ...]) -> None:
        super().__init__()
        self.header = header
        self.warnings = warnings

    def render(self) -> RenderableType:
        look = self.look
        dot = look.muted(f" {look.glyphs.dot} ")
        text = Text(end="")
        h = self.header
        if h is None:
            text.append_text(look.muted("No sandbox header was recorded."))
        else:
            pieces: list[Text] = [look.muted("image ") + fmt.safe_text(h.image, single_line=True)]
            if h.network:
                pieces.append(
                    look.mark(WARNING, word=False) + Text(" network open", style=look.style("warn"))
                )
            else:
                pieces.append(look.muted("network ") + Text("blocked"))
            if h.memory:
                pieces.append(look.muted("memory ") + fmt.safe_text(h.memory, single_line=True))
            if h.cpus is not None:
                pieces.append(Text(_cpus(h.cpus)))
            for index, piece in enumerate(pieces):
                if index:
                    text.append_text(dot)
                text.append_text(piece)
        for warning in self.warnings:
            text.append("\n")
            text.append_text(look.mark(WARNING, word=False))
            text.append(" ")
            text.append_text(fmt.safe_text(warning, single_line=True, style=look.style("warn")))
        return text


class StepList(ScrollView, can_focus=True):
    """The scrolling rows. The cursor is a position in `steps`, not a sandbox index."""

    DEFAULT_CSS = """
    StepList {
        height: 1fr;
        background: $surface;
        scrollbar-size-vertical: 1;
    }
    """

    HELP_GROUP = "Trajectory"
    BINDINGS = [
        Binding("enter,space", "toggle", "Expand"),
        Binding("n", "flagged(1)", "Next flagged"),
        Binding("N", "flagged(-1)", "Prev flagged"),
        Binding("m", "more", "Show more"),
        Binding("down,j", "move(1)", "Down", show=False),
        Binding("up,k", "move(-1)", "Up", show=False),
        Binding("g,home", "edge(0)", "Top", show=False),
        Binding("G,end", "edge(1)", "Bottom", show=False),
        Binding("pagedown", "page(1)", "Page down", show=False),
        Binding("pageup", "page(-1)", "Page up", show=False),
    ]

    cursor: reactive[int] = reactive(0, init=False)

    def __init__(
        self, steps: tuple[TrajectoryStep, ...], *, open_step: int | None = None, id: str | None = None
    ) -> None:
        super().__init__(id=id)
        self.steps = steps
        self.expanded: set[int] = set()
        self.full: set[int] = set()
        self._lines: list[Line] = []
        self._rows: dict[int, int] = {}
        self._width = 0
        self._columns = Layout(1, MIN_COMMAND_WIDTH, 0, False)
        self._jump_to: int | None = None
        pos = None if open_step is None else self.position_of(open_step)
        if pos is not None:
            self.set_reactive(StepList.cursor, pos)
            self.expanded.add(pos)
            self._jump_to = pos

    @property
    def lines(self) -> list[Line]:
        return self._lines

    @property
    def current(self) -> TrajectoryStep | None:
        return self.steps[self.cursor] if self.steps else None

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self.refresh())
        self._rebuild()

    def on_resize(self, event: Resize) -> None:
        if event.size.width != self._width:
            self._rebuild()
            self._reveal()
        if self._jump_to is not None and self._jump_to in self._rows:
            self.scroll_to(y=self._rows[self._jump_to], animate=False, immediate=True)
            self._jump_to = None

    def watch_cursor(self) -> None:
        self.refresh()

    def position_of(self, index: int) -> int | None:
        """Where the step with sandbox index `index` sits in `steps`."""
        return next((pos for pos, step in enumerate(self.steps) if step.index == index), None)

    def show_step(self, index: int) -> bool:
        """Put the cursor on the step with sandbox index `index`, open it and scroll it to the top."""
        pos = self.position_of(index)
        if pos is None:
            return False
        self.cursor = pos
        self.expanded.add(pos)
        self._rebuild()
        self.scroll_to(y=self._rows[pos], animate=False, immediate=True)
        return True

    def action_toggle(self) -> None:
        if not self.steps:
            return
        if self.cursor in self.expanded:
            self.expanded.discard(self.cursor)
        else:
            self.expanded.add(self.cursor)
        self._rebuild()
        self._reveal(whole=True)

    def action_more(self) -> None:
        if not self.steps:
            return
        self.expanded.add(self.cursor)
        if self.cursor in self.full:
            self.full.discard(self.cursor)
        else:
            self.full.add(self.cursor)
        self._rebuild()
        self._reveal()

    def action_move(self, delta: int) -> None:
        if self.steps:
            self.cursor = max(0, min(len(self.steps) - 1, self.cursor + delta))
            self._reveal()

    def action_edge(self, end: int) -> None:
        if self.steps:
            self.cursor = len(self.steps) - 1 if end else 0
            self._reveal()

    def action_page(self, direction: int) -> None:
        if not self.steps:
            return
        target = self._rows[self.cursor] + direction * max(self._view_height() - 1, 1)
        rows = sorted(self._rows.items(), key=lambda item: item[1])
        if direction > 0:
            pos = next((p for p, y in rows if y >= target), len(self.steps) - 1)
        else:
            pos = next((p for p, y in reversed(rows) if y <= target), 0)
        self.cursor = pos
        self._reveal()

    def action_flagged(self, direction: int) -> None:
        flagged = [pos for pos, step in enumerate(self.steps) if step.flagged]
        if not flagged:
            self.app.notify("No step was flagged by Cheat Catcher.", markup=False)
            return
        if direction > 0:
            pos = next((p for p in flagged if p > self.cursor), flagged[0])
        else:
            pos = next((p for p in reversed(flagged) if p < self.cursor), flagged[-1])
        self.cursor = pos
        self._reveal()

    def on_click(self, event: Click) -> None:
        line = self.scroll_offset.y + event.y - HEADER_ROWS
        if 0 <= line < len(self._lines):
            pos = self._lines[line].step
            if self._lines[line].kind == "row" and pos == self.cursor:
                self.action_toggle()
            else:
                self.cursor = pos

    def _view_height(self) -> int:
        return max(self.size.height - HEADER_ROWS, 1)

    def _reveal(self, *, whole: bool = False) -> None:
        if not self.steps:
            return
        top = self._rows[self.cursor]
        bottom = top
        if whole:
            following = [y for p, y in self._rows.items() if p > self.cursor]
            bottom = (min(following) if following else len(self._lines)) - 1
        height = self._view_height()
        y = self.scroll_offset.y
        if top < y:
            y = top
        elif bottom >= y + height:
            y = min(top, bottom - height + 1)
        if y != self.scroll_offset.y:
            self.scroll_to(y=y, animate=False, immediate=True)

    def _plan_columns(self, width: int) -> Layout:
        digits = max((len(str(s.index)) for s in self.steps), default=1)
        roomy = width >= ROOMY_WIDTH
        fixed = 1 + digits + KIND_WIDTH + EXIT_WIDTH + GAP * FIXED_GAPS + ((TIME_WIDTH + GAP) if roomy else 0)
        widest = 0
        for step in self.steps:
            marks = step_marks(step)
            size = sum(
                GAP + MARK_PREFIX + len(m.word) + (len(extra) + 1 if extra else 0) for m, extra in marks
            )
            widest = max(widest, size)
        free = max(width - fixed, 0)
        needed = max((cell_len(fmt.visible(step_target(s))) for s in self.steps), default=0)
        marks = min(widest, max(free - min(needed, free // MARKS_SHARE), 0))
        command = max(width - fixed - marks, MIN_COMMAND_WIDTH)
        return Layout(digits, command, marks, roomy)

    def _rebuild(self) -> None:
        width = max(self.size.width - 1, 1)
        self._columns = self._plan_columns(width)
        self._width = self.size.width
        lines: list[Line] = []
        rows: dict[int, int] = {}
        body = max(width - INDENT - LABEL_WIDTH, 1)
        for pos, step in enumerate(self.steps):
            rows[pos] = len(lines)
            lines.append(Line("row", pos))
            if pos in self.expanded:
                lines.extend(self._detail(pos, step, body))
        self._lines = lines
        self._rows = rows
        self.virtual_size = Size(width, len(lines) + HEADER_ROWS)
        self.refresh()

    def _detail(self, pos: int, step: TrajectoryStep, width: int) -> list[Line]:
        sections = [
            ("command", step.command or ""),
            ("path", step.path or ""),
            ("stdout", step.stdout),
            ("stderr", step.stderr),
            ("content", step.content),
        ]
        out: list[Line] = []
        limit = None if pos in self.full else MAX_SHOWN_LINES
        hidden = 0
        for label, value in sections:
            if not value:
                continue
            wrapped: list[str] = []
            for raw in fmt.visible(value).expandtabs(fmt.TAB_WIDTH).splitlines() or [""]:
                wrapped.extend(chop_cells(raw, width) or [""])
            shown = wrapped if limit is None else wrapped[:limit]
            hidden += len(wrapped) - len(shown)
            for n, chunk in enumerate(shown):
                out.append(Line("label" if n == 0 else "text", pos, chunk, label if n == 0 else ""))
            if len(shown) < len(wrapped):
                left = fmt.plural(len(wrapped) - len(shown), "more line")
                out.append(Line("more", pos, f"{left} in {label}"))
        if not out:
            out.append(Line("note", pos, "No command, output or content was recorded for this step."))
        if hidden:
            out.append(Line("note", pos, "Press m to show all of it."))
        elif pos in self.full:
            out.append(Line("note", pos, "Press m to cut it short again."))
        return out

    def _column_header(self, look: Look, layout: Layout, width: int) -> Strip:
        muted = look.style("muted") + Style(bold=True)
        cells = [
            f"{'#':>{layout.index}}",
            f"{'kind':<{KIND_WIDTH}}",
            f"{'command or path':<{layout.command}}",
            f"{'exit':>{EXIT_WIDTH}}",
        ]
        if layout.roomy:
            cells.append(f"{'time':>{TIME_WIDTH}}")
        if layout.marks:
            cells.append("marks")
        text = (" " * GAP).join(cells)
        return Strip([Segment(f" {text}", self.rich_style + muted)]).crop_extend(0, width, self.rich_style)

    def _row(self, step: TrajectoryStep, look: Look, layout: Layout) -> list[Segment]:
        base = self.rich_style
        muted = base + look.style("muted")
        ellipsis = look.glyphs.ellipsis
        target = fmt.visible(step_target(step))
        if cell_len(target) > layout.command:
            target = chop_cells(target, max(layout.command - len(ellipsis), 1))[0] + ellipsis
        target_style = base if step.command or step.path else muted
        pad = " " * GAP
        segments = [
            Segment(f" {step.index:>{layout.index}}{pad}", muted),
            Segment(f"{fmt.visible(step.kind)[:KIND_WIDTH]:<{KIND_WIDTH}}{pad}", base + look.style("accent")),
            Segment(target or fmt.MISSING, target_style),
            Segment(" " * max(layout.command - cell_len(target or fmt.MISSING), 0) + pad, base),
        ]
        if step.exit_code is None:
            segments.append(Segment(f"{fmt.MISSING:>{EXIT_WIDTH}}", muted))
        elif step.exit_code == 0:
            segments.append(Segment(f"{0:>{EXIT_WIDTH}}", muted))
        else:
            shown = f"{look.symbol(FAILED)} {step.exit_code}"
            segments.append(Segment(f"{shown:>{EXIT_WIDTH}}", base + look.style("plain", bold=True)))
        if layout.roomy:
            segments.append(Segment(f"{pad}{fmt.duration(step.duration):>{TIME_WIDTH}}", muted))
        room = layout.marks
        for mark, extra in step_marks(step):
            room -= GAP
            if room <= len(ellipsis):
                break
            label = f"{look.symbol(mark)} {mark.word}{' ' + extra if extra else ''}"
            if len(label) > room:
                label = label[: room - len(ellipsis)] + ellipsis
            segments.append(Segment(pad + label, base + look.style(mark.tone)))
            room -= len(label)
        return segments

    def _detail_line(self, line: Line, look: Look) -> list[Segment]:
        base = self.rich_style
        muted = base + look.style("muted")
        gutter = Segment(" " * (INDENT - GUTTER_SIDES) + ("|" if look.ascii else "│") + " ", muted)
        if line.kind in ("more", "note"):
            text = f"{look.glyphs.ellipsis} {line.text}" if line.kind == "more" else line.text
            return [gutter, Segment(" " * LABEL_WIDTH), Segment(text, muted)]
        label = f"{line.label:<{LABEL_WIDTH}}"
        return [gutter, Segment(label, muted), Segment(line.text, base)]

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        look = look_for(self)
        layout = self._columns
        if y < HEADER_ROWS:
            return self._column_header(look, layout, width)
        index = self.scroll_offset.y + y - HEADER_ROWS
        if index >= len(self._lines):
            return Strip.blank(width, self.rich_style)
        line = self._lines[index]
        if line.kind == "row":
            segments = self._row(self.steps[line.step], look, layout)
        else:
            segments = self._detail_line(line, look)
        strip = Strip(segments).crop_extend(0, width, self.rich_style)
        if line.kind == "row" and line.step == self.cursor:
            name = "block-cursor-background" if self.has_focus else "block-cursor-blurred-background"
            colour = solid_color(self.app.theme_variables, name)
            strip = strip.apply_style(Style(bgcolor=colour) if colour else Style(reverse=True))
        return strip

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


class Timeline(Vertical):
    """A `Trajectory` as a header line and a list of steps. See the module docstring."""

    DEFAULT_CSS = """
    Timeline {
        height: 1fr;
    }
    """

    def __init__(
        self,
        trajectory: Trajectory,
        *,
        open_step: int | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.trajectory = trajectory
        self.open_step = open_step

    def compose(self) -> ComposeResult:
        yield TimelineHeader(self.trajectory.header, self.trajectory.warnings)
        if self.trajectory.steps:
            yield StepList(self.trajectory.steps, open_step=self.open_step)
        else:
            yield EmptyState(NO_STEPS)

    def on_mount(self) -> None:
        if self.open_step is not None and (steps := self.step_list) is not None:
            steps.focus()

    @property
    def flagged(self) -> int:
        return sum(1 for step in self.trajectory.steps if step.flagged)

    @property
    def step_list(self) -> StepList | None:
        found = self.query(StepList)
        return found.first() if found else None

    def show_step(self, index: int) -> bool:
        """Scroll to the step with sandbox index `index` and open it. False when there's no such step."""
        steps = self.step_list
        if steps is None:
            return False
        steps.focus()
        return steps.show_step(index)
