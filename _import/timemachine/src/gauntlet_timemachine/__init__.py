"""gauntlet-timemachine: replay, rewind, branch and browse recorded agent runs."""

from .diff import StepSummary, TrajectoryDiff, diff
from .replay import Divergence, ReplayError, ReplayReport, apply_step, branch, replay
from .viewer import render_html

__all__ = [
    "Divergence",
    "ReplayError",
    "ReplayReport",
    "StepSummary",
    "TrajectoryDiff",
    "apply_step",
    "branch",
    "diff",
    "render_html",
    "replay",
]
__version__ = "0.1.0"
