"""Extra sample data for the Run screen: calibration results, rotted tasks and mixed categories.

    source = runs_source(violations=("oracle didn't resolve hukkin__tomli-318",))
    source = runs_source(split_categories=True)    # every policy row twice, as swe and lht

`RunsSource.run` behaves like the store: a shipped summary run has no interval, no tamper counts
and no calibration check.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from gauntlet.tui.models import PolicyRow, RunDetail

from .factories import FakeSource, make_source


@dataclass
class RunsSource(FakeSource):
    violations: tuple[str, ...] = ()
    rotted: tuple[tuple[str, str], ...] = ()
    split_categories: bool = False

    def run(self, run_id: str) -> RunDetail:
        detail = super().run(run_id)
        shipped = detail.summary.detail == "summary"
        rows: list[PolicyRow] = []
        for row in detail.policies:
            if shipped:
                row = replace(row, pass_at_1=None, tampered=None)
            if self.split_categories:
                rows.extend(replace(row, category=category) for category in ("lht", "swe"))
            else:
                rows.append(replace(row, category="swe"))
        return replace(
            detail,
            policies=tuple(rows),
            calibration_checked=not shipped,
            violations=() if shipped else self.violations,
            rotted=() if shipped else self.rotted,
        )


def runs_source(**overrides: Any) -> RunsSource:
    base = make_source()
    values: dict[str, Any] = {
        "task_rows": base.task_rows,
        "episode_rows": base.episode_rows,
        "run_ids": base.run_ids,
        "dataset_ids": base.dataset_ids,
    }
    values.update(overrides)
    return RunsSource(**values)
