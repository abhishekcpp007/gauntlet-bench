"""Dataset: one task set.

The full screen shows the set's numbers, the funnel from PRs collected to tasks kept (rejected by
stage), tasks by repo, and its tasks. Today it shows the set's facts.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from .. import format as fmt
from ..models import DatasetDetail
from ..widgets.facts import Fact, Facts
from .base import DataScreen


class DatasetScreen(DataScreen[DatasetDetail]):
    what = "the dataset"

    def __init__(self, dataset_id: str) -> None:
        super().__init__()
        self.dataset_id = dataset_id
        self.crumb = dataset_id

    def fetch(self) -> DatasetDetail:
        return self.source.dataset(self.dataset_id)

    def build(self, data: DatasetDetail) -> Iterable[Widget]:
        yield Facts(
            [
                Fact("Dataset", data.summary.id),
                Fact("Title", data.summary.title),
                Fact("Tasks", fmt.count(data.summary.tasks)),
            ]
        )

    def copy_target(self) -> tuple[str, str] | None:
        return self.dataset_id, "dataset id"
