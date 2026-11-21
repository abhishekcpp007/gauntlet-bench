from pathlib import Path

import pytest
from textual.widgets import Input, SelectionList, Switch

from gauntlet.tui.jobtypes import JobSpec, Step
from gauntlet.tui.widgets.form import FieldRow, FormBanner, FormView, ReviewButton
from gauntlet.tui.widgets.pickers import PathPicker, Picker
from gauntlet.tui.workbench.base import (
    ActionForm,
    BuildError,
    Choice,
    ChoiceField,
    DateField,
    FieldError,
    IntegerField,
    MultiChoiceField,
    NumberField,
    PathField,
    RunField,
    SwitchField,
    TaskField,
    TaskSetField,
    TextField,
    Values,
    repo_name,
)

from .factories import LIVE, screen_text
from .workfakes import fill, form_app, row_errors

SIZE = (120, 40)
BAD_TITLE = "[red]x[/red]"


class EveryKind(ActionForm):
    action_id = "every-kind"
    title = "Every kind"
    group = "check"
    description = "One field of each kind."
    fields = (
        TextField(name="repo", label="Repo", hint="owner/name", validate=repo_name),
        IntegerField(name="count", label="Count", hint="1 to 5", default=2, minimum=1, maximum=5),
        NumberField(name="ratio", label="Ratio", hint="0 to 1", required=False, minimum=0.0, maximum=1.0),
        DateField(name="since", label="Since", hint="a date", required=False),
        ChoiceField(
            name="runner", label="Runner", choices=(Choice("py", "Python"), Choice("js", "JS")), default="py"
        ),
        SwitchField(name="dry", label="Dry run"),
        MultiChoiceField(
            name="policies", label="Policies", choices=(Choice("oracle", "oracle"), Choice("noop", "noop"))
        ),
        PathField(name="patch", label="Patch", required=False),
        TaskSetField(name="tasks", label="Task set", required=False),
        TaskField(name="task", label="Task", task_set="tasks", required=False),
        RunField(name="run", label="Run", required=False),
    )

    def build(self, values: Values) -> JobSpec:
        if values.flag("dry") and values.integer("count") == 1:
            raise BuildError("A dry run needs at least two tasks.")
        return JobSpec(action=self.action_id, title=BAD_TITLE, steps=(Step("check", ("check",)),))


def capture_reviews(view: FormView, monkeypatch: pytest.MonkeyPatch) -> list[JobSpec]:
    posted: list[JobSpec] = []
    send = view.post_message

    def post(message):
        if isinstance(message, FormView.Reviewed):
            posted.append(message.spec)
            return True
        return send(message)

    monkeypatch.setattr(view, "post_message", post)
    return posted


def test_text_fields_validate_and_split():
    field = TextField(name="repo", label="Repo", validate=repo_name)
    assert field.check(" pallets/click ") == "pallets/click"
    with pytest.raises(FieldError, match="owner/name"):
        field.check("click")
    with pytest.raises(FieldError, match="Repo is needed"):
        field.check("  ")
    several = TextField(name="p", label="P", several=True, required=False)
    assert several.check("a.py, b.py  c.py") == ("a.py", "b.py", "c.py")
    assert several.check("") is None


def test_numbers_check_their_range():
    count = IntegerField(name="n", label="Workers", minimum=1, maximum=8)
    assert count.check("3") == 3
    with pytest.raises(FieldError, match="whole number"):
        count.check("2.5")
    with pytest.raises(FieldError, match="from 1 to 8"):
        count.check("9")
    assert IntegerField(name="n", label="N", minimum=0).check("0") == 0
    with pytest.raises(FieldError, match="0 or more"):
        IntegerField(name="n", label="N", minimum=0).check("-1")
    with pytest.raises(FieldError, match="10 or less"):
        IntegerField(name="n", label="N", maximum=10).check("11")
    ratio = NumberField(name="r", label="Ratio", minimum=0.0, maximum=1.0)
    assert ratio.check("0.5") == 0.5
    with pytest.raises(FieldError, match="a number"):
        ratio.check("half")


def test_dates_must_be_real():
    field = DateField(name="d", label="Since")
    assert field.check("2026-11-05") == "2026-11-05"
    with pytest.raises(FieldError, match="look like"):
        field.check("05/11/2026")
    with pytest.raises(FieldError, match="real date"):
        field.check("2026-02-30")


def test_paths_check_kind_and_existence(tmp_path: Path):
    patch = tmp_path / "fix.diff"
    patch.write_text("diff")
    must = PathField(name="p", label="Patch")
    assert must.check(str(patch)) == patch
    with pytest.raises(FieldError, match="no file"):
        must.check(str(tmp_path / "missing.diff"))
    with pytest.raises(FieldError, match="is a folder"):
        must.check(str(tmp_path))
    new_folder = PathField(name="o", label="Out", kind="folder", must_exist=False)
    assert new_folder.check(str(tmp_path / "new")) == tmp_path / "new"
    with pytest.raises(FieldError, match="is a file"):
        new_folder.check(str(patch))


def test_choices_switches_and_pickers():
    assert SwitchField(name="s", label="S").check(False) is False
    multi = MultiChoiceField(name="m", label="Policies")
    assert multi.check(["oracle"]) == ("oracle",)
    with pytest.raises(FieldError, match="at least one of policies"):
        multi.check(())
    with pytest.raises(FieldError, match="Task set is needed"):
        TaskSetField(name="t", label="Task set").check(None)
    assert RunField(name="r", label="Run").check("golden") == "golden"


def test_values_read_each_kind():
    values = Values(
        Path("w"), {"t": "x", "n": 3, "f": 0.5, "b": True, "p": Path("a"), "i": ("a", "b"), "o": None}
    )
    assert values.text("t") == "x" and values.integer("n") == 3 and values.number("f") == 0.5
    assert values.flag("b") and values.path("p") == Path("a") and values.items("i") == ("a", "b")
    assert values.text("o") is None and values.items("o") == () and values.integer("o") is None
    assert values.items("t") == ("x",) and values["n"] == 3


async def test_draws_every_kind_with_labels_and_hints():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        assert len(view.query(FieldRow)) == len(EveryKind.fields)
        kinds = [type(row.control) for row in view.rows]
        assert Switch in kinds and SelectionList in kinds and PathPicker in kinds and Picker in kinds
        text = screen_text(app)
        for label in ("Repo", "Count", "Dry run", "Policies", "Task set", "Run"):
            assert label in text
        assert "owner/name" in text and "1 to 5" in text


async def test_tab_moves_field_to_field_in_order():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        view.focus_first()
        await pilot.pause()
        seen = []
        for _ in view.rows:
            seen.append(next(row.field.name for row in view.rows if app.focused in row.query("*")))
            await pilot.press("tab")
        assert seen == [field.name for field in EveryKind.fields]
        assert isinstance(app.focused, ReviewButton)
        await pilot.press("shift+tab")
        assert app.focused in view.row("run").query("*")


async def test_leaving_a_field_checks_it_and_fixing_clears_it():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        view.focus_first()
        await pilot.press(*"click", "tab")
        await pilot.pause()
        assert "owner/name" in row_errors(view)["repo"]
        assert "! error" in screen_text(app)
        fill(view, repo="pallets/click")
        await pilot.pause()
        assert "repo" not in row_errors(view)


async def test_review_reports_every_error_and_focuses_the_first():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, repo="", count="9", since="yesterday", policies=())
        assert view.review() is None
        await pilot.pause()
        assert set(row_errors(view)) == {"repo", "count", "since", "policies"}
        assert isinstance(app.focused, Input) and app.focused in view.row("repo").query("*")


async def test_a_good_form_posts_its_spec(monkeypatch):
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        posted = capture_reviews(view, monkeypatch)
        fill(view, repo="pallets/click", count="2", tasks=LIVE)
        spec = view.review()
        assert spec is not None and posted == [spec]
        assert spec.title == BAD_TITLE


async def test_a_build_error_shows_on_top():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        fill(view, repo="pallets/click", count="1", dry=True)
        assert view.review() is None
        await pilot.pause()
        banner = view.query_one(FormBanner)
        assert banner.error == "A dry run needs at least two tasks."
        assert "Can't build this job" in screen_text(app)


async def test_a_blocked_form_says_why_and_wont_post(monkeypatch):
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        posted = capture_reviews(view, monkeypatch)
        view.set_blocked("Docker isn't running.")
        fill(view, repo="pallets/click")
        assert view.review() is None
        await pilot.pause()
        assert posted == []
        assert "Can't start yet" in screen_text(app) and "Docker isn't running." in screen_text(app)


async def test_enter_on_the_last_text_field_reviews(monkeypatch):
    class OneField(ActionForm):
        action_id = "one"
        title = "One"
        group = "score"
        description = "One field."
        fields = (TextField(name="name", label="Name"),)

        def build(self, values: Values) -> JobSpec:
            return JobSpec(action="one", title="One", steps=(Step("one", ("report",)),))

    app = form_app(OneField())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        reviewed: list[bool] = []
        monkeypatch.setattr(view, "review", lambda: reviewed.append(True))
        view.focus_first()
        await pilot.press(*"x", "enter")
        assert reviewed == [True]


async def test_choosing_a_task_set_lists_its_tasks():
    app = form_app(EveryKind())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        view = app.query_one(FormView)
        task = view.row("task").control
        assert isinstance(task, Picker)
        fill(view, tasks=LIVE)
        await pilot.pause()
        assert {c.value for c in task.fetch()} == {
            t.instance_id for t in app.query_one(FormView).source().tasks(dataset=LIVE)
        }
        assert task.value is None


async def test_choices_from_the_data_load_in_a_thread():
    def policies(source):
        return tuple(Choice(p.id, p.id) for p in source.reference().policies)

    class Loaded(ActionForm):
        action_id = "loaded"
        title = "Loaded"
        group = "check"
        description = "Choices from the data."
        fields = (MultiChoiceField(name="policies", label="Policies", options=policies),)

    app = form_app(Loaded())
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        control = app.query_one(FormView).row("policies").control
        assert isinstance(control, SelectionList)
        assert "oracle" in control.selected and len(control.selected) == control.option_count > 1
