"""Pieces more than one screen shows. The run cells (its detail, its oracle and its violations)
take the record and the active `Look`, so they fit `Column(render=...)`. `calibration_rules`
words the calibration thresholds the same way on the Run and Reference screens."""

from __future__ import annotations

from rich.text import Text

from . import format as fmt
from .models import RunSummary, Thresholds
from .theme import SUMMARY_ONLY, WARNING, Look, check_mark
from .widgets.definitions import Definition


def run_oracle(run: RunSummary, look: Look) -> Text:
    """`✓ 7/7`: how many oracle episodes resolved, marked by whether they all did."""
    if run.oracle is None:
        return look.muted(fmt.MISSING)
    text = look.mark(check_mark(run.oracle.resolved == run.oracle.episodes), word=False)
    text.append(f" {fmt.ratio(run.oracle.resolved, run.oracle.episodes)}")
    return text


def run_violations(run: RunSummary, look: Look) -> Text:
    """`✓ none`, `▲ 2`, or `not checked` when the run wasn't held to the calibration rule."""
    if run.violations is None:
        return look.muted("not checked")
    if run.violations == 0:
        return look.mark(check_mark(True), word=False) + Text(" none", end="")
    return look.mark(WARNING, word=False) + Text(f" {fmt.count(run.violations)}", end="")


def run_detail(run: RunSummary, look: Look) -> Text:
    """`full`, or `◌ summary` for shipped rows that left the full record out."""
    return look.mark(SUMMARY_ONLY) if run.detail == "summary" else Text("full", end="")


def calibration_rules(thresholds: Thresholds) -> list[Definition]:
    """What `gauntlet calibrate` holds a run to, one rule per kind of policy."""
    oracle, noop, cheat = (
        fmt.reward(value).strip()
        for value in (thresholds.oracle_min_reward, thresholds.noop_reward, thresholds.cheat_max_reward)
    )
    return [
        Definition("oracle", f"The real fix has to resolve and score at least {oracle}."),
        Definition("noop", f"Doing nothing has to score exactly {noop}."),
        Definition("cheats", f"No cheat may resolve or score above {cheat}."),
    ]
