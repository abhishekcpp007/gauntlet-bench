"""Report: a run's leaderboard from `gauntlet report`, drawn as tables, and an HTML page if you
want one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget

from .. import actions
from ..jobtypes import JobRecord, JobSpec
from ..widgets.reportview import ReportOutcome, ReportScreen
from .base import ActionForm, DateField, FieldError, RunField, SwitchField, Values, register

if TYPE_CHECKING:
    from ..app import GauntletApp


@register
class Report(ActionForm):
    action_id = "report"
    fields = (
        RunField(
            name="run",
            label="Run",
            hint="A run with a results file. Shipped summary rows can't be reported on.",
            results=True,
        ),
        DateField(
            name="cutoff",
            label="Cutoff date",
            hint="Optional. Splits each pass rate into before and after this date, to spot contamination.",
            required=False,
        ),
        SwitchField(
            name="html",
            label="HTML page too",
            hint="Also write the leaderboard as a page in the workspace's reports folder.",
        ),
    )

    def build(self, values: Values) -> JobSpec:
        results = values.path("run")
        if results is None:
            raise FieldError("Pick a run with a results file.")
        return actions.report(
            values.workspace, results, cutoff=values.text("cutoff"), html=values.flag("html")
        )

    def outcome(self, record: JobRecord) -> Widget | None:
        return ReportOutcome(record) if record.state == "succeeded" else None

    def after(self, job: JobRecord, app: GauntletApp) -> bool:
        app.push_screen(ReportScreen(job.id, job.spec.title))
        return True
