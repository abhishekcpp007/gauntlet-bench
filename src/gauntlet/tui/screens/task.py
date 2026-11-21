"""Task: one task in full.

The full screen has facts (repo, PR, merged date, category, runner, image, fingerprint) and tabs
for the statement, tests, leak check, patches, episodes and, on LHT tasks, the horizon. Today it
shows the task's facts.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from ..models import TaskDetail
from ..widgets.facts import Fact, Facts
from .base import DataScreen


class TaskScreen(DataScreen[TaskDetail]):
    what = "the task"

    def __init__(self, instance_id: str) -> None:
        super().__init__()
        self.instance_id = instance_id
        self.crumb = instance_id

    def fetch(self) -> TaskDetail:
        return self.source.task(self.instance_id)

    def build(self, data: TaskDetail) -> Iterable[Widget]:
        yield Facts(
            [
                Fact("Instance", data.row.instance_id),
                Fact("Dataset", data.row.dataset_id),
                Fact("Repo", data.row.repo),
                Fact("PR", data.row.pr_title),
            ]
        )

    def copy_target(self) -> tuple[str, str] | None:
        return self.instance_id, "instance id"
