"""`OutcomeView`: what a finished job found, from its log. A scan's verdict and each finding, or
how many problems a check found, in the same marks the episode screen uses."""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text

from .. import format as fmt
from ..actions import FINDING_MARKERS, Outcome
from ..models import Finding
from ..theme import ERROR, FOUND, SEVERITIES, VERDICTS, Look
from .themed import Themed

MARK_GAP = 1
NO_FINDINGS = "No rule fired. The patch looks like an honest fix."


def finding_lines(finding: Finding, look: Look) -> list[Text]:
    head = Text.assemble((finding.rule, "bold"), "  ", fmt.safe_text(finding.message, single_line=True))
    where = [
        part for part in (finding.file, f"step {finding.step}" if finding.step is not None else None) if part
    ]
    lines = [head]
    if where:
        lines.append(look.muted(f" {look.glyphs.dot} ".join(where)))
    if finding.evidence:
        lines.append(fmt.safe_text(finding.evidence, single_line=True, style=look.palette.muted))
    return lines


class OutcomeView(Themed):
    """See the module docstring. `action` names the check, so its marker can be named."""

    DEFAULT_CSS = """
    OutcomeView {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.outcome: Outcome | None = None
        self.action = ""

    def show(self, outcome: Outcome, action: str) -> None:
        self.outcome = outcome
        self.action = action
        self.refresh(layout=True)

    def render(self) -> RenderableType:
        look = self.look
        outcome = self.outcome
        if outcome is None:
            return Text("")
        if outcome.scan_error is not None:
            return Text.assemble(look.mark(ERROR, word=False), " ", fmt.safe_text(outcome.scan_error))
        if outcome.scan is None:
            marker = FINDING_MARKERS.get(self.action, "").strip()
            problems = fmt.plural(outcome.found, "problem")
            return Text.assemble(
                look.mark(FOUND),
                f"  The check found {problems}. The lines that start with {marker} in the log say which.",
            )
        scan = outcome.scan
        grid = Table.grid(padding=(0, MARK_GAP))
        grid.add_column(no_wrap=True)
        grid.add_column(ratio=1)
        count = fmt.plural(len(scan.findings), "finding")
        grid.add_row(look.mark(VERDICTS[scan.verdict]), look.muted(count))
        if not scan.findings:
            grid.add_row(Text(""), look.muted(NO_FINDINGS))
        for finding in scan.findings:
            lines = finding_lines(finding, look)
            grid.add_row(look.mark(SEVERITIES[finding.severity]), lines[0])
            for line in lines[1:]:
                grid.add_row(Text(""), line)
        return grid
