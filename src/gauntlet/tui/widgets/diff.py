"""`DiffView`: a unified diff with file headers, line numbers and `+`/`-` marks.

Patches come from agents, so every line is shown literally: no markup is read and control
characters are drawn in caret form. Lines are rendered on demand, so a long patch scrolls fast,
and past `MAX_DIFF_LINES` the rest is cut with a note saying how much was left out.
`n` and `p` jump to the next and previous file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from rich.cells import cell_len
from rich.segment import Segment
from rich.style import Style
from textual.binding import Binding
from textual.color import Color, ColorParseError
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip

from .. import format as fmt
from ..theme import Look, look_for, solid_color

MAX_DIFF_LINES = 5000
ROW_TINT = 0.14
GUTTER_GAP = 1
NUMBER_COLUMNS = 2

LineKind = Literal["file", "hunk", "add", "del", "ctx", "meta", "note"]

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT_HEADER = re.compile(r"^diff --git a/(.*) b/(.*)$")
_SIDE_PREFIX = re.compile(r"^[ab]/")
_STATUS = ("new file mode", "deleted file mode", "rename from")
_HIDDEN_META = ("index ", "similarity index ", "rename to ", "old mode ", "new mode ")


@dataclass(frozen=True, slots=True)
class DiffLine:
    kind: LineKind
    text: str
    old: int | None = None
    new: int | None = None


@dataclass(slots=True)
class DiffFile:
    path: str
    line: int
    added: int = 0
    removed: int = 0
    status: str = ""


@dataclass(slots=True)
class ParsedDiff:
    files: list[DiffFile] = field(default_factory=list)
    lines: list[DiffLine] = field(default_factory=list)
    dropped: int = 0
    max_number: int = 0

    @property
    def truncated(self) -> bool:
        return self.dropped > 0


def _path_from_header(line: str) -> str:
    path = line[4:].split("\t", 1)[0].strip()
    return _SIDE_PREFIX.sub("", path)


def parse_diff(patch: str, *, max_lines: int = MAX_DIFF_LINES) -> ParsedDiff:
    """Split a unified diff into files and lines. File counts cover the whole patch, the kept
    lines stop at `max_lines`."""
    parsed = ParsedDiff()
    raw = patch.splitlines()
    current: DiffFile | None = None
    from_git = False
    minus_path: str | None = None
    old = new = old_left = new_left = 0

    def keep(line: DiffLine) -> None:
        if len(parsed.lines) < max_lines:
            parsed.lines.append(line)
        else:
            parsed.dropped += 1

    def open_file(path: str) -> DiffFile:
        diff_file = DiffFile(path=path, line=len(parsed.lines))
        parsed.files.append(diff_file)
        keep(DiffLine("file", path))
        return diff_file

    for line in raw:
        if old_left > 0 or new_left > 0:
            sign, body = line[:1], line[1:]
            if sign == "+" and new_left > 0:
                keep(DiffLine("add", body, new=new))
                parsed.max_number = max(parsed.max_number, new)
                new, new_left = new + 1, new_left - 1
                if current is not None:
                    current.added += 1
                continue
            if sign == "-" and old_left > 0:
                keep(DiffLine("del", body, old=old))
                parsed.max_number = max(parsed.max_number, old)
                old, old_left = old + 1, old_left - 1
                if current is not None:
                    current.removed += 1
                continue
            if sign in (" ", ""):
                keep(DiffLine("ctx", body, old=old, new=new))
                parsed.max_number = max(parsed.max_number, old, new)
                old, new, old_left, new_left = old + 1, new + 1, old_left - 1, new_left - 1
                continue
            if sign != "\\":
                old_left = new_left = 0
        if git := _GIT_HEADER.match(line):
            current, from_git = open_file(git.group(2)), True
        elif line.startswith("--- "):
            minus_path = _path_from_header(line)
        elif line.startswith("+++ "):
            plus_path = _path_from_header(line)
            if not from_git:
                current = open_file(minus_path if plus_path == "/dev/null" and minus_path else plus_path)
        elif hunk := _HUNK.match(line):
            old, old_left = int(hunk.group(1)), int(hunk.group(2) or 1)
            new, new_left = int(hunk.group(3)), int(hunk.group(4) or 1)
            from_git = False
            keep(DiffLine("hunk", line))
        elif current is not None and line.startswith(_STATUS):
            current.status = line.split(" mode", 1)[0].split(" from", 1)[0]
        elif not line.startswith(_HIDDEN_META):
            keep(DiffLine("meta", line))
    return parsed


def _tint(base: str | None, over: str | None) -> str | None:
    if not base or not over:
        return None
    try:
        return Color.parse(base).blend(Color.parse(over), ROW_TINT).hex
    except ColorParseError:
        return None


class DiffView(ScrollView, can_focus=True):
    """A scrolling unified diff. Give it the patch text, or None for no patch."""

    DEFAULT_CSS = """
    DiffView {
        height: 1fr;
        background: $surface;
        scrollbar-size-vertical: 1;
    }
    """

    HELP_GROUP = "Patch"
    BINDINGS = [
        Binding("n", "next_file", "Next file"),
        Binding("p", "previous_file", "Prev file"),
        Binding("j", "scroll_down", "Down", show=False),
        Binding("k", "scroll_up", "Up", show=False),
        Binding("g", "scroll_home", "Top", show=False),
        Binding("G", "scroll_end", "Bottom", show=False),
    ]

    def __init__(
        self,
        patch: str | None,
        *,
        empty: str = "No patch.",
        max_lines: int = MAX_DIFF_LINES,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.empty = empty
        self.max_lines = max_lines
        self.diff = ParsedDiff()
        self._rows: list[DiffLine] = []
        self._cache: dict[int, tuple[Strip, Style]] = {}
        self.set_patch(patch)

    def set_patch(self, patch: str | None) -> None:
        self.diff = parse_diff(patch or "", max_lines=self.max_lines)
        rows = list(self.diff.lines)
        if not rows:
            rows = [DiffLine("note", self.empty)]
        elif self.diff.truncated:
            shown = len(self.diff.lines)
            shown, total = fmt.count(shown), fmt.count(shown + self.diff.dropped)
            rows.insert(0, DiffLine("note", f"Large patch: showing the first {shown} of {total} lines."))
        self._rows = rows
        self._cache.clear()
        width = max((cell_len(fmt.visible(r.text).expandtabs(fmt.TAB_WIDTH)) for r in rows), default=0)
        self.virtual_size = Size(width + self._gutter_width() + GUTTER_GAP * 2 + 1, len(rows))
        self.refresh()

    @property
    def file_lines(self) -> list[int]:
        offset = 1 if self.diff.truncated else 0
        return [i for i, r in enumerate(self._rows) if r.kind == "file" and i >= offset]

    @property
    def current_file(self) -> str | None:
        top = self.scroll_offset.y
        files = self.file_lines
        if not files:
            return None
        current = files[0]
        for index in files:
            if index <= top:
                current = index
        return self._rows[current].text

    def on_mount(self) -> None:
        self.app.theme_changed_signal.subscribe(self, lambda _theme: self._repaint())

    def _repaint(self) -> None:
        self._cache.clear()
        self.refresh()

    def action_next_file(self) -> None:
        top = self.scroll_offset.y
        following = [i for i in self.file_lines if i > top]
        if following:
            self.scroll_to(y=following[0], animate=False)

    def action_previous_file(self) -> None:
        top = self.scroll_offset.y
        earlier = [i for i in self.file_lines if i < top]
        if earlier:
            self.scroll_to(y=earlier[-1], animate=False)

    def _gutter_width(self) -> int:
        return len(str(self.diff.max_number)) if self.diff.max_number else 1

    def render_line(self, y: int) -> Strip:
        index = self.scroll_offset.y + y
        width = self.size.width
        base = self.rich_style
        if index >= len(self._rows):
            return Strip.blank(width, base)
        cached = self._cache.get(index)
        if cached is None:
            cached = self._render_row(self._rows[index], look_for(self), base)
            self._cache[index] = cached
        strip, fill = cached
        x = self.scroll_offset.x
        return strip.crop(x, x + width).extend_cell_length(width, fill)

    def _render_row(self, row: DiffLine, look: Look, base: Style) -> tuple[Strip, Style]:
        """One row, and the style that fills the rest of its width."""
        variables = self.app.theme_variables
        muted, good, bad = look.style("muted"), look.style("good"), look.style("bad")
        text = fmt.visible(row.text).expandtabs(fmt.TAB_WIDTH)
        digits = self._gutter_width()
        pad = " " * GUTTER_GAP
        if row.kind == "note":
            return Strip([Segment(f"{pad}{text}", base + muted)]), base
        if row.kind == "file":
            diff_file = next(f for f in self.diff.files if f.path == row.text)
            header = base + Style(bgcolor=solid_color(variables, "panel"), bold=True)
            counts = f"  +{diff_file.added} -{diff_file.removed}"
            status = f"  {diff_file.status}" if diff_file.status else ""
            plain = header + muted + Style(bold=False)
            segments = [
                Segment(f"{pad}{look.glyphs.bullet} ", header + look.style("accent")),
                Segment(text, header),
                Segment(counts, plain),
                Segment(status, plain),
            ]
            return Strip(segments), header
        if row.kind in ("hunk", "meta"):
            gutter = " " * (digits * NUMBER_COLUMNS + GUTTER_GAP)
            return Strip([Segment(f"{pad}{gutter}{pad}  {text}", base + muted)]), base
        old = "" if row.old is None else str(row.old)
        new = "" if row.new is None else str(row.new)
        gutter = f"{pad}{old:>{digits}} {new:>{digits}}{pad}"
        if row.kind == "add":
            tone, sign, bg = (
                good,
                "+",
                _tint(solid_color(variables, "surface"), solid_color(variables, "success")),
            )
        elif row.kind == "del":
            tone, sign, bg = (
                bad,
                "-",
                _tint(solid_color(variables, "surface"), solid_color(variables, "error")),
            )
        else:
            tone, sign, bg = Style(), " ", None
        row_style = base + Style(bgcolor=bg) if bg else base
        segments = [
            Segment(gutter, row_style + muted),
            Segment(f"{sign} ", row_style + tone + Style(bold=True)),
            Segment(text, row_style + tone),
        ]
        return Strip(segments), row_style
