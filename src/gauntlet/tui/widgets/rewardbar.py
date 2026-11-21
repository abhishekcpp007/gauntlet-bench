"""`RewardBar`: how an episode's reward was made, as a bar, a small table and one plain sentence.

It explains the numbers the harness recorded and never recomputes the reward. The paths follow
`gauntlet.harness.reward.compute_reward`: a patch that's empty or didn't apply and a cheating
verdict both set the reward to the penalty before any part is worked out; otherwise the reward is
the weighted sum of tests, rubric and similarity, capped at 0 when no target test passed. When
the recorded parts don't add up to the recorded reward, it says so instead of forcing the sum.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.console import RenderableType
from rich.style import Style
from rich.table import Table
from rich.text import Text
from textual.color import Color, ColorParseError

from .. import format as fmt
from ..models import RewardBreakdown, Verdict
from ..theme import Look
from .themed import Themed

PatchState = Literal["applied", "empty", "failed"]

SENTENCE_NAMES = {"tests": "tests", "rubric": "the rubric", "similarity": "similarity"}
ROUNDING = 0.5 * 10**-fmt.REWARD_DIGITS
MAX_BAR_WIDTH = 72
MIN_BAR_WIDTH = 10
BAR_MARGIN = 10
PART_SHADES = (1.0, 0.7, 0.45)
COLUMN_GAP = 2
EARNED = "█"
UNEARNED = "░"
ASCII_EARNED = "#"
ASCII_UNEARNED = "."
TIMES = "×"
ASCII_TIMES = "x"


@dataclass(frozen=True, slots=True)
class Part:
    """One weighted part. `weight` is None when the row didn't record it."""

    name: str
    value: float
    weight: float | None
    scored: bool = True

    @property
    def contribution(self) -> float | None:
        return None if self.weight is None else self.weight * self.value


Note = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class Explanation:
    """What the bar shows: the path the reward took, its parts, the notes under the table and
    the one sentence."""

    path: Literal["none", "penalty", "unweighted", "weighted"]
    parts: tuple[Part, ...]
    notes: tuple[Note, ...]
    sentence: str
    adds_up: bool = True
    total: float | None = None


def _phrase(parts: tuple[Part, ...]) -> str:
    pieces = [
        f"{p.contribution or 0.0:.{fmt.REWARD_DIGITS}f} from {SENTENCE_NAMES[p.name]}"
        for p in parts
        if p.weight and p.scored and round(p.contribution or 0.0, fmt.REWARD_DIGITS)
    ]
    if not pieces:
        return "nothing"
    if len(pieces) == 1:
        return pieces[0]
    return f"{', '.join(pieces[:-1])} and {pieces[-1]}"


def _penalty_sentence(reward: float, verdict: Verdict, patch: PatchState | None) -> str:
    shown = fmt.reward(reward).strip()
    tail = f"so the reward is {shown} and the parts don't count."
    if patch == "empty":
        return f"The agent's patch was empty, {tail}"
    if patch == "failed":
        return f"The agent's patch didn't apply, {tail}"
    if verdict == "cheating" and patch == "applied":
        return f"Cheat Catcher's verdict was cheating, {tail}"
    if verdict == "cheating":
        return f"Cheat Catcher's verdict was cheating (or the patch was empty or didn't apply), {tail}"
    return f"The patch was empty or didn't apply, {tail}"


def explain(
    breakdown: RewardBreakdown | None,
    reward: float,
    verdict: Verdict,
    resolved: bool,
    *,
    patch: PatchState | None = None,
) -> Explanation:
    """The reward's story from what was recorded. Pure, so every path is easy to test."""
    shown = fmt.reward(reward).strip()
    if breakdown is None:
        return Explanation(
            "none", (), (), f"No breakdown was recorded for this episode, only the reward of {shown}."
        )
    b = breakdown
    if b.penalty:
        notes = (("penalty", fmt.reward(b.penalty), "replaces the weighted parts, which weren't worked out"),)
        sentence = _penalty_sentence(reward, verdict, patch)
        if abs(b.penalty - reward) > ROUNDING:
            sentence = (
                f"A penalty of {fmt.reward(b.penalty).strip()} was recorded, but the recorded reward is "
                f"{shown}. The breakdown doesn't explain the gap, so this shows the recorded reward."
            )
            return Explanation("penalty", (), notes, sentence, adds_up=False)
        return Explanation("penalty", (), notes, sentence)

    weighted = b.w_tests is not None or b.w_similarity is not None or b.w_rubric is not None
    rubric_missing = weighted and b.w_rubric is None
    parts = (
        Part("tests", b.tests, b.w_tests),
        Part("rubric", b.rubric, b.w_rubric, scored=not rubric_missing),
        Part("similarity", b.similarity, b.w_similarity),
    )
    notes: list[Note] = []
    if b.milestones_done is not None:
        notes.append(
            (
                "milestones",
                f"{b.milestones_done}",
                "done. On a long-horizon task the tests part is the mean milestone pass rate times "
                "the P2P rate.",
            )
        )
    if not weighted:
        sentence = (
            f"The weights weren't recorded for this row, so only the parts and the recorded "
            f"reward of {shown} are shown."
        )
        return Explanation("unweighted", parts, tuple(notes), sentence)

    total = sum(p.contribution or 0.0 for p in parts if p.scored)
    if b.capped_from is not None:
        notes.append(
            (
                "cap",
                fmt.reward(reward),
                f"no target test passed, so it's capped from {fmt.reward(b.capped_from).strip()}",
            )
        )
        target = b.capped_from
    else:
        target = reward
    if abs(total - target) > ROUNDING:
        sentence = (
            f"The parts add up to {fmt.reward(total).strip()}, but the recorded reward is {shown}. "
            "The breakdown doesn't explain the gap, so this shows the recorded reward."
        )
        return Explanation("weighted", parts, tuple(notes), sentence, adds_up=False, total=total)

    phrase = _phrase(parts)
    if b.capped_from is not None:
        sentence = (
            f"No target test passed, so the reward is capped at {shown}. Without the cap "
            f"{phrase} would make {fmt.reward(b.capped_from).strip()}."
        )
    elif resolved:
        sentence = f"Every target test passed and nothing broke: {phrase} make {shown}."
    elif b.tests > 0 and b.milestones_done is not None:
        sentence = f"Some milestones passed, so tests earned partial credit: {phrase} make {shown}."
    elif b.tests > 0:
        sentence = f"Some target tests passed, so tests earned partial credit: {phrase} make {shown}."
    else:
        sentence = f"Tests earned nothing: {phrase} make {shown}."
    return Explanation("weighted", parts, tuple(notes), sentence, total=total)


def _shade(look: Look, factor: float) -> Style:
    try:
        accent = Color.parse(look.palette.accent)
        muted = Color.parse(look.palette.muted)
    except ColorParseError:
        return look.style("accent")
    if accent.ansi is not None or muted.ansi is not None:
        return look.style("accent")
    return Style(color=muted.blend(accent, factor).hex)


def _cells(parts: tuple[Part, ...], width: int) -> list[tuple[Part, int, int]]:
    """Each part's (earned, total) cells on a 0 to 1 scale, rounded so the edges line up."""
    out: list[tuple[Part, int, int]] = []
    start = 0.0
    for part in parts:
        weight = part.weight or 0.0
        value = max(0.0, min(1.0, part.value)) if part.scored else 0.0
        left, right = round(start * width), round((start + weight) * width)
        earned = round((start + weight * value) * width) - left
        out.append((part, earned, right - left))
        start += weight
    return out


class RewardBar(Themed):
    """The reward as weighted parts. Give it the breakdown, the reward, the verdict and whether it
    resolved; pass `patch` ("applied", "empty" or "failed") so a penalty can say which one hit."""

    DEFAULT_CSS = """
    RewardBar {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(
        self,
        breakdown: RewardBreakdown | None,
        reward: float,
        verdict: Verdict,
        resolved: bool,
        *,
        patch: PatchState | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.breakdown = breakdown
        self.reward = reward
        self.verdict = verdict
        self.resolved = resolved
        self.explanation = explain(breakdown, reward, verdict, resolved, patch=patch)

    @property
    def sentence(self) -> str:
        return self.explanation.sentence

    def _bar(self, look: Look) -> Text:
        width = max(MIN_BAR_WIDTH, min(MAX_BAR_WIDTH, self.size.width - BAR_MARGIN))
        earned_glyph = ASCII_EARNED if look.ascii else EARNED
        unearned_glyph = ASCII_UNEARNED if look.ascii else UNEARNED
        bar = Text(end="", no_wrap=True)
        labels = Text(end="", no_wrap=True)
        used = 0
        for (part, earned, total), shade in zip(
            _cells(self.explanation.parts, width), PART_SHADES, strict=True
        ):
            if total <= 0:
                continue
            bar.append(earned_glyph * earned, style=_shade(look, shade))
            bar.append(unearned_glyph * (total - earned), style=look.style("muted"))
            label = part.name if len(part.name) < total else part.name[: max(total - 1, 0)]
            labels.append_text(look.muted(f"{label:<{total}}"))
            used += total
        bar.append(unearned_glyph * (width - used), style=look.style("muted"))
        bar.append("  ")
        bar.append_text(look.reward(self.reward, bold=True))
        labels.append_text(look.muted(" " * (width - used)))
        scale = look.muted(f"{'0':<{width - 1}}1")
        out = Text(end="")
        for line in (bar, labels, scale):
            out.append_text(line)
            out.append("\n")
        return out

    def _table(self, look: Look) -> Table:
        e = self.explanation
        grid = Table.grid(padding=(0, COLUMN_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(justify="right", no_wrap=True)
        grid.add_column()
        number = fmt.REWARD_DIGITS
        for part in e.parts:
            if not part.scored:
                grid.add_row(
                    look.muted(part.name),
                    look.muted(fmt.MISSING),
                    look.muted("not scored: its weight went to the other parts"),
                )
            elif part.weight is None:
                grid.add_row(
                    look.muted(part.name), Text(f"{part.value:.{number}f}"), look.muted("weight not recorded")
                )
            else:
                times = ASCII_TIMES if look.ascii else TIMES
                sum_text = Text(f"{times} {part.weight:.{number}f} = ", style=look.style("muted"))
                sum_text.append(
                    f"{part.contribution or 0.0:.{number}f}", style=look.style("plain", bold=True)
                )
                grid.add_row(look.muted(part.name), Text(f"{part.value:.{number}f}"), sum_text)
        for label, value, note in e.notes:
            tone = "bad" if label == "penalty" else "warn" if label == "cap" else "muted"
            grid.add_row(
                Text(label, style=look.style(tone)), Text(value, style=look.style(tone)), look.muted(note)
            )
        if e.total is not None and (
            not e.adds_up or self.breakdown and self.breakdown.capped_from is not None
        ):
            grid.add_row(look.muted("parts add up to"), look.reward(e.total), Text(""))
        recorded = Text("reward" if e.adds_up and e.path != "unweighted" else "recorded reward", end="")
        grid.add_row(recorded, look.reward(self.reward, bold=True), Text(""))
        return grid

    def render(self) -> RenderableType:
        look = self.look
        e = self.explanation
        out = Table.grid()
        out.add_column()
        out.add_row(Text(e.sentence, style=look.style("plain", bold=True)))
        if e.path != "none":
            out.add_row(Text(""))
        if e.path == "weighted":
            out.add_row(self._bar(look))
        if e.path != "none":
            out.add_row(self._table(look))
        return out
