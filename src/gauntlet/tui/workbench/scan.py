"""Scan a patch: Cheat Catcher's rules on a diff, and on the agent's steps if you have them."""

from __future__ import annotations

from textual.widget import Widget

from .. import actions
from ..jobtypes import JobRecord, JobSpec
from ..widgets.outcome import scan_outcome
from .base import ActionForm, FieldError, PathField, TextField, Values, register


@register
class ScanPatch(ActionForm):
    action_id = "scan_patch"
    fields = (
        PathField(name="patch", label="Patch file", hint="The unified diff to scan."),
        TextField(
            name="protect",
            label="Protected tests",
            hint="Optional. Test files the grader owns, as paths in the repo, with spaces between.",
            placeholder="tests/test_parser.py",
            required=False,
            several=True,
        ),
        PathField(
            name="trajectory",
            label="Trajectory",
            hint="Optional. The agent's steps, a .jsonl from a run folder's trajectories.",
            required=False,
        ),
    )

    def outcome(self, record: JobRecord) -> Widget | None:
        return scan_outcome(record)

    def build(self, values: Values) -> JobSpec:
        patch = values.path("patch")
        if patch is None:
            raise FieldError("Pick the patch file.")
        return actions.scan_patch(
            patch, protect=values.items("protect"), trajectory=values.path("trajectory")
        )
