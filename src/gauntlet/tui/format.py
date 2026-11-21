"""Plain text helpers: rewards, numbers, durations, dates, truncation, and safe untrusted text.

Everything here is pure and has no Textual in it. `safe_text` is how agent-written text (patches,
commands, outputs, statements) reaches the screen: always literal, never markup, and with control
characters shown instead of sent to the terminal.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rich.text import Text

MISSING = "-"
ELLIPSIS = "…"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
REWARD_DIGITS = 2
PERCENT = 100
TAB_WIDTH = 4

_DEL = 0x7F
_C0_END = 0x20
_C1_START = 0x80
_C1_END = 0xA0
_CARET_OFFSET = 0x40
_KEPT_CONTROLS = frozenset("\n\t")


def reward(value: float) -> str:
    """`+0.97`, `-1.00`, and ` 0.00` for zero, so a column of rewards lines up on the point."""
    rounded = round(value, REWARD_DIGITS)
    if rounded == 0:
        return f" {0:.{REWARD_DIGITS}f}"
    return f"{rounded:+.{REWARD_DIGITS}f}"


def percent(value: float | None, *, digits: int = 0) -> str:
    """A fraction from 0 to 1 as a percentage: `0.973` is `97%`."""
    if value is None:
        return MISSING
    return f"{value * PERCENT:.{digits}f}%"


def count(value: int | None) -> str:
    return MISSING if value is None else f"{value:,}"


def ratio(part: int, whole: int) -> str:
    """`5/7`, with thousands separators."""
    return f"{part:,}/{whole:,}"


def plural(n: int, word: str, many: str | None = None) -> str:
    """`1 task`, `3 tasks`, `2 policies` (pass `many` when adding an s is wrong)."""
    noun = word if n == 1 else (many or f"{word}s")
    return f"{n:,} {noun}"


def duration(seconds: float | None) -> str:
    """`0.4 s`, `4.2 s`, `3 m 05 s`, `1 h 02 m`."""
    if seconds is None or seconds < 0:
        return MISSING
    if seconds < SECONDS_PER_MINUTE:
        return f"{seconds:.1f} s"
    whole = int(seconds)
    if whole < SECONDS_PER_HOUR:
        minutes, rest = divmod(whole, SECONDS_PER_MINUTE)
        return f"{minutes} m {rest:02d} s"
    hours, rest = divmod(whole, SECONDS_PER_HOUR)
    return f"{hours} h {rest // SECONDS_PER_MINUTE:02d} m"


def _parse(value: str | float | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def date(value: str | float | None) -> str:
    """An ISO timestamp or epoch seconds as `2026-11-05`. Anything unreadable is `-`."""
    parsed = _parse(value)
    return parsed.date().isoformat() if parsed else MISSING


def date_time(value: str | float | None) -> str:
    """`2026-11-05 14:03`, in the timestamp's own offset (UTC for epoch seconds)."""
    parsed = _parse(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else MISSING


def date_range(start: str | float | None, end: str | float | None) -> str:
    """`2026-09-07 to 2026-10-30`, or one date when both ends fall on the same day."""
    first, last = date(start), date(end)
    if first == MISSING and last == MISSING:
        return MISSING
    if first == last or last == MISSING:
        return first
    if first == MISSING:
        return last
    return f"{first} to {last}"


def middle(value: str, width: int, ellipsis: str = ELLIPSIS) -> str:
    """Cut `value` to `width` characters by dropping its middle, so both ends stay readable."""
    if len(value) <= width:
        return value
    if width <= len(ellipsis):
        return value[:width]
    keep = width - len(ellipsis)
    head = (keep + 1) // 2
    tail = keep - head
    return f"{value[:head]}{ellipsis}{value[len(value) - tail :] if tail else ''}"


def visible(value: str) -> str:
    """`value` with every control character but newline and tab shown in caret form (`^[`)."""
    out: list[str] = []
    for ch in value:
        code = ord(ch)
        if ch in _KEPT_CONTROLS:
            out.append(ch)
        elif code < _C0_END:
            out.append(f"^{chr(code + _CARET_OFFSET)}")
        elif code == _DEL:
            out.append("^?")
        elif _C1_START <= code < _C1_END:
            out.append(f"\\x{code:02x}")
        else:
            out.append(ch)
    return "".join(out)


def one_line(value: str) -> str:
    """`value` on a single line: runs of whitespace, newlines included, become one space."""
    return " ".join(value.split())


def safe_text(value: object, *, style: str = "", single_line: bool = False) -> Text:
    """Untrusted text as a literal `Text`: no markup is read and control characters are shown."""
    raw = "" if value is None else str(value)
    shown = visible(one_line(raw) if single_line else raw).expandtabs(TAB_WIDTH)
    return Text(shown, style=style, end="")
