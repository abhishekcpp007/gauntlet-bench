"""From a release range: list a repo's release ranges, pick some, and build one long task from each.

It's one form in two stages. "List ranges" runs `gauntlet ranges` and fills the Ranges field when
it ends; Review then builds the picked ranges with `gauntlet build-lht`. When the build ends, its
Result pane says which ranges became tasks and why the rest didn't.
"""

from __future__ import annotations

from collections.abc import Sequence

from textual.widget import Widget

from .. import actions
from ..actions import ReleaseRange
from ..jobtypes import FINISHED, JobRecord, JobSpec, Output
from ..widgets.buildresult import BuildResult, built_outputs
from ..widgets.form import FormView
from ..widgets.formextras import FormNote
from ..widgets.rangelister import ListFields, RangeLister
from .base import (
    ActionForm,
    ChoiceField,
    FieldError,
    IntegerField,
    MultiChoiceField,
    SwitchField,
    TextField,
    Values,
    register,
    repo_name,
)
from .make_tasks import SCOPES

FIELDS = ListFields(repo="repo", repo_url="repo_url", last="last", prereleases="prereleases", ranges="ranges")
ABOUT = (
    "A range is the work between two release tags, say v1.2.0 to v1.3.0. The agent starts at the "
    "first tag and has to reach the second."
)
RARELY_KEPT = (
    "Many ranges don't make a task, and that's normal: a range has to pass the same checks a PR does."
)


@register
class MakeLhtTasks(ActionForm):
    """See the module docstring. `listed` is the repo, clone URL and ranges the last listing found."""

    action_id = "make_lht_tasks"
    fields = (
        TextField(
            name=FIELDS.repo,
            label="Repo",
            hint="The GitHub repo, written owner/name.",
            placeholder="pallets/click",
            validate=repo_name,
        ),
        TextField(
            name=FIELDS.repo_url,
            label="Clone from",
            hint="Optional. A git URL or a folder to clone in place of GitHub. A folder needs no network.",
            required=False,
        ),
        IntegerField(
            name=FIELDS.last,
            label="Newest ranges",
            hint="Optional. List only this many of the newest ranges. Empty lists them all.",
            required=False,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_LAST,
        ),
        SwitchField(
            name=FIELDS.prereleases,
            label="Prereleases",
            hint="Count rc, alpha and beta tags as releases too.",
        ),
        MultiChoiceField(
            name=FIELDS.ranges,
            label="Ranges",
            hint="The ranges to build, once they're listed. Each one you pick becomes one long task.",
            default=(),
            required=False,
        ),
        IntegerField(
            name="fix_runs",
            label="Fix runs",
            hint="How often the release is run, to catch flaky tests.",
            default=actions.FIX_RUNS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_FIX_RUNS,
        ),
        TextField(
            name="python",
            label="Python",
            hint="The Python version the task's environment is built with.",
            default=actions.PYTHON,
        ),
        IntegerField(
            name="max_prs",
            label="Max PRs",
            hint="Skip a range with more PRs and direct commits that change source than this.",
            default=actions.LHT_MAX_PRS,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_LHT_PRS,
        ),
        IntegerField(
            name="max_gold_lines",
            label="Max gold lines",
            hint="Skip a range whose source diff, the real fix, has more changed lines than this.",
            default=actions.LHT_MAX_GOLD_LINES,
            minimum=actions.AT_LEAST_ONE,
            maximum=actions.MAX_GOLD_LINES,
        ),
        ChoiceField(
            name="scope",
            label="Test scope",
            hint="Full runs the whole suite, so the tests guard what the release didn't touch too.",
            choices=SCOPES,
            default=actions.SCOPE,
        ),
        TextField(
            name="name",
            label="Task set name",
            hint="Optional. Empty lets the workspace pick one from the repo and the time.",
            required=False,
        ),
    )

    def __init__(self) -> None:
        self.listed: tuple[str, str | None, tuple[ReleaseRange, ...]] | None = None

    def outcome(self, record: JobRecord) -> Widget | None:
        return BuildResult(record, note=RARELY_KEPT) if record.state in FINISHED else None

    def openable(self, record: JobRecord) -> tuple[Output, ...]:
        return built_outputs(record)

    def extras(self, view: FormView) -> Sequence[tuple[Widget, str | None]]:
        return (
            (FormNote(ABOUT, id="lht-about"), None),
            (RangeLister(view, FIELDS, self.remember), FIELDS.prereleases),
        )

    def remember(self, repo: str, url: str | None, ranges: tuple[ReleaseRange, ...]) -> None:
        self.listed = (repo, url, ranges)

    def picked(self, values: Values) -> tuple[ReleaseRange, ...]:
        """The ranges picked, from the listing of the repo and clone URL the form holds now."""
        repo = values.text(FIELDS.repo) or ""
        typed = values.text(FIELDS.repo_url)
        if self.listed is None:
            raise FieldError("List the repo's release ranges first, then pick the ones to build.")
        listed_repo, listed_url, ranges = self.listed
        url = actions.check_repo_url(typed) if typed else None
        if (repo, url) != (listed_repo, listed_url):
            raise FieldError(f"The ranges below are {listed_repo}'s. List the ranges of {repo} first.")
        chosen = set(values.items(FIELDS.ranges))
        if not chosen:
            raise FieldError("Pick at least one release range to build.")
        return tuple(r for r in ranges if r.spec in chosen)

    def build(self, values: Values) -> JobSpec:
        ranges = self.picked(values)
        fix_runs = values.integer("fix_runs")
        python = values.text("python")
        max_prs = values.integer("max_prs")
        max_gold_lines = values.integer("max_gold_lines")
        scope = values.text("scope")
        if fix_runs is None or python is None or max_prs is None or max_gold_lines is None or scope is None:
            raise FieldError("Fill in the fix runs, the Python version, both limits and the scope.")
        return actions.make_lht_tasks(
            values.workspace,
            values.text(FIELDS.repo) or "",
            ranges=ranges,
            repo_url=values.text(FIELDS.repo_url),
            python=python,
            fix_runs=fix_runs,
            max_prs=max_prs,
            max_gold_lines=max_gold_lines,
            scope=scope,
            name=values.text("name"),
        )
