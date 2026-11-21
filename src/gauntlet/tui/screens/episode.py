"""Episode: why this score.

The full screen has facts (task, policy, the reward large on the diverging scale, verdict,
resolved, steps, time) and tabs for the reward, evidence, tests, rubric, patch, trajectory and
provenance. Today it shows the episode's facts.
"""

from __future__ import annotations

from collections.abc import Iterable

from textual.widget import Widget

from ..models import EpisodeDetail
from ..theme import VERDICTS
from ..widgets.facts import Fact, Facts
from .base import DataScreen


class EpisodeScreen(DataScreen[EpisodeDetail]):
    what = "the episode"

    def __init__(self, run_id: str, episode_id: str) -> None:
        super().__init__()
        self.run_id = run_id
        self.episode_id = episode_id
        self.crumb = episode_id

    def fetch(self) -> EpisodeDetail:
        return self.source.episode(self.run_id, self.episode_id)

    def build(self, data: EpisodeDetail) -> Iterable[Widget]:
        look = self.gauntlet.look
        yield Facts(
            [
                Fact("Episode", data.row.episode_id),
                Fact("Task", data.row.instance_id),
                Fact("Policy", data.row.policy),
                Fact("Reward", look.reward(data.row.reward), copy=f"{data.row.reward}"),
                Fact("Verdict", look.mark(VERDICTS[data.row.cheat_verdict]), copy=data.row.cheat_verdict),
            ]
        )

    def copy_target(self) -> tuple[str, str] | None:
        return self.episode_id, "episode id"
