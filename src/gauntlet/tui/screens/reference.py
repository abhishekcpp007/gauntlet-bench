"""Reference (`4`): the trust story as a reference.

The grading steps, the leak checks, the Cheat Catcher rules, the cheat policies and the
calibration thresholds, one tab each. Everything comes from `DataSource.reference()`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import Static, TabbedContent, TabPane

from ..cells import calibration_rules
from ..models import Reference, ReferenceItem
from ..widgets.definitions import Definition, Definitions
from .base import DataScreen

INTROS = {
    "grading": "What the grader does with a patch once an episode ends, in this order.",
    "leaks": (
        "Every task passes all of these before it ships. Together they show the sandbox can't see the answer."
    ),
    "rules": (
        "Cheat Catcher reads the patch and the agent's own steps. A high finding makes the verdict cheating."
    ),
    "policies": (
        "Calibration plays these on every sampled task. The oracle has to win and every cheat has to lose."
    ),
    "thresholds": "gauntlet calibrate fails the run when any of these breaks.",
}


def _definitions(items: Sequence[ReferenceItem], *, by_title: bool = False) -> Definitions:
    rows = [Definition(item.title if by_title else item.id, item.what) for item in items]
    return Definitions(rows, numbered=by_title)


class ReferenceScreen(DataScreen[Reference]):
    crumb = "Reference"
    what = "the reference"

    def fetch(self) -> Reference:
        return self.source.reference()

    def build(self, data: Reference) -> Iterable[Widget]:
        panes = [
            (
                "grading",
                f"Grading {len(data.grading_steps)}",
                _definitions(data.grading_steps, by_title=True),
            ),
            ("leaks", f"Leak checks {len(data.leak_checks)}", _definitions(data.leak_checks)),
            ("rules", f"Cheat Catcher {len(data.rules)}", _definitions(data.rules)),
            ("policies", f"Policies {len(data.policies)}", _definitions(data.policies)),
            ("thresholds", "Thresholds", Definitions(calibration_rules(data.thresholds))),
        ]
        tabs = TabbedContent(id="reference-tabs")
        for pane_id, title, body in panes:
            intro = Static(INTROS[pane_id], markup=False, classes="intro")
            tabs.compose_add_child(TabPane(title, VerticalScroll(intro, body), id=pane_id))
        yield tabs
