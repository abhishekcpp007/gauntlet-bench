"""Table cells that more than one screen shows for a run: its detail, its oracle and its
violations. Each takes the record and the active `Look`, so it fits `Column(render=...)`."""

from __future__ import annotations

from rich.text import Text

from . import format as fmt
from .models import RunSummary
from .theme import SUMMARY_ONLY, WARNING, Look, check_mark


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
