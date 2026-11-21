"""The viewer's two themes and its status vocabulary, in one place.

Every status the viewer shows (a verdict, resolved or not, a severity, a leak check) is a `Mark`:
a symbol, a word and a tone. Colour only ever adds to the symbol and the word, so the screen still
reads with `NO_COLOR=1`. A `Look` turns marks and rewards into styled `Text` for the active theme,
with either the Unicode or the ASCII symbol set. Widgets get one with `look_for(self)` and never
name a colour or a symbol themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.style import Style
from rich.text import Text
from textual.color import Color, ColorParseError
from textual.dom import DOMNode
from textual.theme import Theme

from . import format as fmt
from .models import Severity, Verdict

Tone = Literal["good", "warn", "bad", "muted", "plain", "accent"]

DARK_THEME = "gauntlet-dark"
LIGHT_THEME = "gauntlet-light"
DEFAULT_THEME = DARK_THEME

REWARD_MIN = -1.0
REWARD_MAX = 1.0

GAUNTLET_DARK = Theme(
    name=DARK_THEME,
    primary="#6CA8F0",
    secondary="#41536B",
    accent="#6CA8F0",
    warning="#E0A84A",
    error="#EE6B6E",
    success="#5DBB7E",
    foreground="#CDD5DF",
    background="#0E1217",
    surface="#141A21",
    panel="#1B232D",
    dark=True,
    variables={
        "foreground-muted": "#7D8896",
        "border": "#6CA8F0",
        "border-blurred": "#2A3441",
        "footer-key-foreground": "#6CA8F0",
        "footer-background": "#141A21",
        "block-cursor-background": "#24344A",
        "block-cursor-foreground": "#E6EDF5",
        "block-cursor-text-style": "none",
        "block-cursor-blurred-background": "#1B232D",
        "block-cursor-blurred-foreground": "#CDD5DF",
        "block-hover-background": "#18202A",
        "input-selection-background": "#6CA8F0 30%",
        "scrollbar": "#2A3441",
        "scrollbar-hover": "#41536B",
        "scrollbar-active": "#6CA8F0",
        "scrollbar-background": "#141A21",
        "scrollbar-background-hover": "#141A21",
        "scrollbar-background-active": "#141A21",
    },
)

GAUNTLET_LIGHT = Theme(
    name=LIGHT_THEME,
    primary="#1F63C4",
    secondary="#9AA9BC",
    accent="#1F63C4",
    warning="#9A6400",
    error="#C42B30",
    success="#1E7B40",
    foreground="#1E252E",
    background="#F7F9FB",
    surface="#FFFFFF",
    panel="#EBEFF4",
    dark=False,
    variables={
        "foreground-muted": "#5F6B7A",
        "border": "#1F63C4",
        "border-blurred": "#CDD5DF",
        "footer-key-foreground": "#1F63C4",
        "footer-background": "#EBEFF4",
        "block-cursor-background": "#D6E4F7",
        "block-cursor-foreground": "#0F141A",
        "block-cursor-text-style": "none",
        "block-cursor-blurred-background": "#EBEFF4",
        "block-cursor-blurred-foreground": "#1E252E",
        "block-hover-background": "#F0F3F7",
        "input-selection-background": "#1F63C4 25%",
        "scrollbar": "#CDD5DF",
        "scrollbar-hover": "#9AA9BC",
        "scrollbar-active": "#1F63C4",
        "scrollbar-background": "#FFFFFF",
        "scrollbar-background-hover": "#FFFFFF",
        "scrollbar-background-active": "#FFFFFF",
    },
)

THEMES: tuple[Theme, ...] = (GAUNTLET_DARK, GAUNTLET_LIGHT)


@dataclass(frozen=True, slots=True)
class Mark:
    """One status as the viewer shows it: `symbol` in Unicode, `ascii` for --ascii, and a word."""

    symbol: str
    ascii: str
    word: str
    tone: Tone


VERDICTS: dict[Verdict, Mark] = {
    "clean": Mark("✓", "+", "clean", "good"),
    "suspicious": Mark("▲", "^", "suspicious", "warn"),
    "cheating": Mark("●", "*", "cheating", "bad"),
}
RESOLVED = Mark("✓", "+", "resolved", "good")
UNRESOLVED = Mark("✗", "x", "not resolved", "muted")
PASSED = Mark("✓", "+", "pass", "good")
FAILED = Mark("✗", "x", "fail", "muted")
SEVERITIES: dict[Severity, Mark] = {
    "low": Mark("○", "o", "low", "muted"),
    "medium": Mark("▲", "^", "medium", "warn"),
    "high": Mark("●", "*", "high", "bad"),
}
LEAK_OK = Mark("✓", "+", "ok", "good")
LEAK_FAILED = Mark("✗", "x", "failed", "bad")
TAMPERED = Mark("✗", "x", "tampered", "bad")
INTACT = Mark("✓", "+", "intact", "good")
ERROR = Mark("!", "!", "error", "bad")
WARNING = Mark("▲", "^", "warning", "warn")
SUMMARY_ONLY = Mark("◌", "-", "summary", "muted")


def resolved_mark(resolved: bool) -> Mark:
    return RESOLVED if resolved else UNRESOLVED


def check_mark(ok: bool) -> Mark:
    return PASSED if ok else FAILED


def leak_mark(ok: bool) -> Mark:
    return LEAK_OK if ok else LEAK_FAILED


def tamper_mark(tampered: bool) -> Mark:
    return TAMPERED if tampered else INTACT


@dataclass(frozen=True, slots=True)
class Glyphs:
    """The non-status symbols: separators, the ellipsis, sort arrows."""

    crumb: str
    dot: str
    ellipsis: str
    ascending: str
    descending: str
    bullet: str
    rule: str
    step: str
    spinner: tuple[str, ...]


UNICODE_GLYPHS = Glyphs(
    crumb="›",
    dot="·",
    ellipsis="…",
    ascending="↑",
    descending="↓",
    bullet="•",
    rule="─",
    step="→",
    spinner=("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"),
)
ASCII_GLYPHS = Glyphs(
    crumb=">",
    dot="|",
    ellipsis="...",
    ascending="^",
    descending="v",
    bullet="*",
    rule="-",
    step=">",
    spinner=("|", "/", "-", "\\"),
)


@dataclass(frozen=True, slots=True)
class Palette:
    """The colours each tone maps to, read from the active theme's variables."""

    good: str
    warn: str
    bad: str
    muted: str
    plain: str
    accent: str

    @classmethod
    def from_variables(cls, variables: dict[str, str]) -> Palette:
        def pick(*names: str, fallback: str) -> str:
            for name in names:
                if (value := solid_color(variables, name)) is not None:
                    return value
            return fallback

        return cls(
            good=pick("text-success", "success", fallback="green"),
            warn=pick("text-warning", "warning", fallback="yellow"),
            bad=pick("text-error", "error", fallback="red"),
            muted=pick("foreground-muted", fallback="bright_black"),
            plain=pick("foreground", fallback="default"),
            accent=pick("text-primary", "primary", fallback="blue"),
        )

    def color(self, tone: Tone) -> str:
        return getattr(self, tone)


def solid_color(variables: dict[str, str], name: str) -> str | None:
    """Theme variable `name` as a colour Rich can draw: see-through colours are laid over the
    background, ANSI colours keep their name. None when it's missing or isn't a colour."""
    value = variables.get(name)
    if value is None:
        return None
    try:
        color = Color.parse(value)
        background = Color.parse(variables.get("background", "black"))
    except ColorParseError:
        return None
    if color.ansi is not None:
        return color.rich_color.name
    if color.a < 1:
        color = background + color
    return color.hex


def _blendable(value: str) -> Color | None:
    """`value` as a colour that can be mixed, or None for an ANSI colour or one that won't parse."""
    try:
        color = Color.parse(value)
    except ColorParseError:
        return None
    return None if color.ansi is not None else color


def reward_color(reward: float, palette: Palette) -> str:
    """Where a reward sits on the diverging scale: -1 red, 0 neutral, +1 green."""
    clamped = max(REWARD_MIN, min(REWARD_MAX, reward))
    end = palette.good if clamped >= 0 else palette.bad
    neutral, target = _blendable(palette.muted), _blendable(end)
    if neutral is None or target is None:
        return end if clamped else palette.muted
    return neutral.blend(target, abs(clamped)).hex


@dataclass(frozen=True, slots=True)
class Look:
    """How things look right now: the active palette and symbol set."""

    palette: Palette
    glyphs: Glyphs
    ascii: bool = False

    def style(self, tone: Tone, *, bold: bool = False) -> Style:
        return Style(color=self.palette.color(tone), bold=bold)

    def symbol(self, mark: Mark) -> str:
        return mark.ascii if self.ascii else mark.symbol

    def mark(self, mark: Mark, *, word: bool = True) -> Text:
        """The mark's symbol, and its word unless `word` is False."""
        label = f"{self.symbol(mark)} {mark.word}" if word else self.symbol(mark)
        return Text(label, style=self.style(mark.tone), no_wrap=True, end="")

    def reward(self, value: float | None, *, bold: bool = False) -> Text:
        if value is None:
            return Text(fmt.MISSING, style=self.style("muted"), end="")
        style = Style(color=reward_color(value, self.palette), bold=bold)
        return Text(fmt.reward(value), style=style, no_wrap=True, end="")

    def muted(self, value: str) -> Text:
        return Text(value, style=self.style("muted"), end="")

    def accent(self, value: str, *, bold: bool = False) -> Text:
        return Text(value, style=self.style("accent", bold=bold), end="")


def make_look(variables: dict[str, str], *, ascii: bool = False) -> Look:
    return Look(Palette.from_variables(variables), ASCII_GLYPHS if ascii else UNICODE_GLYPHS, ascii)


def look_for(node: DOMNode) -> Look:
    """The look for the app a widget belongs to. Works under any Textual app."""
    app = node.app
    variables: dict[str, str] = getattr(app, "theme_variables", {})
    return make_look(variables, ascii=bool(getattr(app, "ascii_mode", False)))
