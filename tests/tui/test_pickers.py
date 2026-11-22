from pathlib import Path

from textual.widgets import DirectoryTree, OptionList

from gauntlet.tui.widgets.pickers import (
    PathBrowser,
    PathPicker,
    Picker,
    PickList,
    run_choices,
    task_choices,
    task_set_choices,
)
from gauntlet.tui.workbench.base import Choice

from .factories import GOLDEN, LHT, LIVE, LIVE_JS, WidgetApp, make_source, screen_text
from .wait import wait_until

SIZE = (100, 30)
HOSTILE = "[red]x[/red]"


def test_choices_come_from_the_data():
    source = make_source()
    assert [c.value for c in task_set_choices(source)] == [LIVE, LIVE_JS, LHT]
    assert {c.value for c in task_choices(source, LHT)} == {t.instance_id for t in source.tasks(dataset=LHT)}
    assert GOLDEN in [c.value for c in run_choices(source)]
    assert task_set_choices(source)[0].detail.endswith("tasks")


async def test_typing_narrows_the_list_and_enter_picks():
    choices = (Choice("a", "alpha", "first"), Choice("b", "beta", "second"), Choice("c", HOSTILE, "third"))
    picker = Picker("Thing", lambda: choices, prompt="pick a thing")
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        assert "pick a thing" in screen_text(pilot.app)
        picker.focus()
        await pilot.press("enter")
        await pilot.pause()
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert isinstance(pilot.app.screen, PickList)
        assert HOSTILE in screen_text(pilot.app)
        await pilot.press(*"sec")
        await pilot.pause()
        assert pilot.app.screen.query_one(OptionList).option_count == 1
        await pilot.press("enter")
        await pilot.pause()
        assert picker.value == "b"
        assert "beta" not in screen_text(pilot.app) and "b" in screen_text(pilot.app)
        await pilot.press("delete")
        assert picker.value is None


async def test_esc_closes_without_a_change_and_nothing_matching_says_so():
    alpha = Choice("a", "alpha")
    picker = Picker("Thing", lambda: (alpha,), choice=alpha)
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.focus()
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        await pilot.press(*"zzz")
        await pilot.pause()
        assert "Nothing matches." in screen_text(pilot.app)
        await pilot.press("escape")
        await pilot.pause()
        assert picker.value == "a"


async def test_an_empty_list_says_theres_nothing_to_pick():
    picker = Picker("Run", lambda: ())
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.focus()
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "There's nothing to pick yet." in screen_text(pilot.app)


async def test_a_failing_list_says_why():
    def broken() -> tuple[Choice, ...]:
        raise OSError("disk gone")

    picker = Picker("Run", broken)
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.focus()
        await pilot.press("enter")
        await pilot.app.workers.wait_for_complete()
        await pilot.pause()
        assert "Couldn't load the choices: OSError: disk gone" in screen_text(pilot.app)


def browser_ready(app) -> bool:
    if not isinstance(app.screen, PathBrowser):
        return False
    return bool(app.screen.query_one(DirectoryTree).root.children)


async def test_browsing_picks_a_file(tmp_path: Path):
    (tmp_path / "fix.diff").write_text("diff")
    picker = PathPicker("file", value=str(tmp_path))
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.input.focus()
        await pilot.press("ctrl+o")
        await wait_until(pilot, lambda: browser_ready(pilot.app), what="the folder tree")
        assert isinstance(pilot.app.screen, PathBrowser)
        tree = pilot.app.screen.query_one(DirectoryTree)
        assert Path(tree.path) == tmp_path
        await pilot.press("down", "enter")
        await pilot.pause()
        assert picker.value == str(tmp_path / "fix.diff")


async def test_browsing_picks_a_folder(tmp_path: Path):
    (tmp_path / "runs").mkdir()
    picker = PathPicker("folder", value=str(tmp_path))
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.input.focus()
        await pilot.press("ctrl+o")
        await wait_until(pilot, lambda: browser_ready(pilot.app), what="the folder tree")
        await pilot.press("down", "s")
        await pilot.pause()
        assert picker.value == str(tmp_path / "runs")


async def test_esc_leaves_the_path_alone(tmp_path: Path):
    picker = PathPicker("file", value=str(tmp_path))
    async with WidgetApp(picker).run_test(size=SIZE) as pilot:
        picker.input.focus()
        await pilot.press("ctrl+o")
        await wait_until(pilot, lambda: browser_ready(pilot.app), what="the folder tree")
        await pilot.press("backspace", "escape")
        await pilot.pause()
        assert picker.value == str(tmp_path)


def test_a_summary_only_run_is_marked_before_you_pick_it():
    from .factories import SHIPPED_LIVE

    details = {c.value: c.detail for c in run_choices(make_source())}
    assert details[SHIPPED_LIVE].endswith("summary only, no report")
    assert details[GOLDEN].endswith("episodes") and "summary" not in details[GOLDEN]
