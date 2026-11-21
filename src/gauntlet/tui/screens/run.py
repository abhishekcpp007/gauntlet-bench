"""Run: one run.

The full screen has tabs for the summary (one row per policy with pass@1 and its interval), the
task by policy matrix, a filterable episode table and the calibration check. Today it shows the
run's facts.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from .. import format as fmt
from ..models import RunDetail
from ..widgets.facts import Fact, Facts
from .base import DataScreen


class RunScreen(DataScreen[RunDetail]):
    what = "the run"

    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.crumb = run_id

    def fetch(self) -> RunDetail:
        return self.source.run(self.run_id)

    def build(self, data: RunDetail) -> Iterable[Widget]:
        yield Facts(
            [
                Fact("Run", data.summary.id),
                Fact("Title", data.summary.title),
                Fact("Episodes", fmt.count(data.summary.episodes)),
            ]
        )

    def copy_target(self) -> tuple[str, str] | None:
        return self.run_id, "run id"
