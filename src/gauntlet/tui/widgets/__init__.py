"""Small reusable widgets. Each carries its own `DEFAULT_CSS` and uses theme variables only.

Status and numbers: `StatusBadge`, `RewardText`, `Stat`. Blocks: `Facts`, `Checklist`. Lists:
`DataGrid` (with `Column`) and `FilterBar` (with `FacetGroup`). Patches: `DiffView`. States:
`EmptyState`, `ErrorState`, `Loading`, and `Deferred`, which loads a pane in a thread and swaps
in its content or an error. Widgets that draw status get symbols and colours from
`gauntlet.tui.theme` through `Themed.look`.
"""

from .checklist import CheckItem, Checklist
from .deferred import Deferred
from .diff import DiffView, parse_diff
from .facts import Fact, Facts
from .filterbar import FacetGroup, FacetPicker, FilterBar
from .grid import Column, DataGrid
from .messages import CopyRequested
from .stat import Stat
from .states import Empty, EmptyState, ErrorState, Loading, describe_error
from .status import RewardText, StatusBadge
from .themed import Themed

__all__ = [
    "CheckItem",
    "Checklist",
    "Column",
    "CopyRequested",
    "DataGrid",
    "Deferred",
    "DiffView",
    "Empty",
    "EmptyState",
    "ErrorState",
    "FacetGroup",
    "FacetPicker",
    "Fact",
    "Facts",
    "FilterBar",
    "Loading",
    "RewardText",
    "Stat",
    "StatusBadge",
    "Themed",
    "describe_error",
    "parse_diff",
]
