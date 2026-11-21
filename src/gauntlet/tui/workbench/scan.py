"""Scan a patch: Cheat Catcher's rules on a diff, and on the agent's steps if you have them."""

from __future__ import annotations

from pathlib import Path

from ..jobtypes import JobSpec, Step
from .base import ActionForm, PathField, TextField, Values, register


# Stand-in until the builders merge: swap scan_spec for the builder in gauntlet.tui.actions.
def scan_spec(patch: Path, protect: tuple[str, ...], trajectory: Path | None) -> JobSpec:
    argv = ["cheatcatcher", "scan", "--patch", str(patch)]
    if protect:
        argv += ["--protect", *protect]
    if trajectory is not None:
        argv += ["--trajectory", str(trajectory)]
    argv.append("--json")
    return JobSpec(
        action=ScanPatch.action_id,
        title=f"Scan {patch.name}",
        steps=(Step("scan", tuple(argv)),),
        exclusive=False,
    )


@register
class ScanPatch(ActionForm):
    action_id = "scan"
    title = "Scan a patch"
    group = "score"
    description = "Check a diff for cheating with Cheat Catcher's rules, the same scan the grader makes."
    cost = "No Docker and no network. Takes a second or two."
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

    def build(self, values: Values) -> JobSpec:
        patch = values.path("patch")
        assert patch is not None
        return scan_spec(patch, values.items("protect"), values.path("trajectory"))
