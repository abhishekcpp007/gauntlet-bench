from textual.widgets import OptionList

from gauntlet.tui.models import Facet
from gauntlet.tui.widgets import FacetGroup, FacetPicker, FilterBar
from gauntlet.tui.widgets.filterbar import Chips, FilterInput

from .factories import WidgetApp, screen_text

GROUPS = (
    FacetGroup("repo", "Repo", (Facet("hukkin/tomli", 3), Facet("mahmoud/boltons", 2))),
    FacetGroup("runner", "Runner", (Facet("pytest", 5),)),
)


class BarApp(WidgetApp):
    def __init__(self, groups=GROUPS) -> None:
        self.bar = FilterBar(groups)
        super().__init__(self.bar)
        self.changes: list[tuple[str, dict[str, str]]] = []

    def on_filter_bar_changed(self, event: FilterBar.Changed) -> None:
        self.changes.append((event.query, event.facets))


async def test_typing_posts_the_query():
    app = BarApp()
    async with app.run_test(size=(80, 10)) as pilot:
        app.bar.focus_input()
        await pilot.press("t", "o", "m")
        await pilot.pause()
        assert app.changes[-1] == ("tom", {})
        assert app.bar.query == "tom"


async def test_escape_clears_the_query():
    app = BarApp()
    async with app.run_test(size=(80, 10)) as pilot:
        app.bar.focus_input()
        await pilot.press("x", "escape")
        await pilot.pause()
        assert app.bar.query == ""
        assert app.changes[-1] == ("", {})


async def test_facet_picker_sets_and_clears_a_facet():
    app = BarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.bar.choose()
        await pilot.pause()
        assert isinstance(app.screen, FacetPicker)
        options = app.screen.query_one(OptionList)
        index = next(
            i
            for i in range(options.option_count)
            if options.get_option_at_index(i).id == "repo\0hukkin/tomli"
        )
        options.highlighted = index
        await pilot.press("enter")
        await pilot.pause()
        assert not isinstance(app.screen, FacetPicker)
        assert app.bar.facets == {"repo": "hukkin/tomli"}
        assert app.changes[-1] == ("", {"repo": "hukkin/tomli"})
        app.bar.set_groups(GROUPS)
        app.bar.set_count(3, 12)
        await pilot.pause()
        text = screen_text(app)
        assert "repo hukkin/tomli" in text and "3 of 12" in text
        app.bar.set_facet("repo", None)
        await pilot.pause()
        assert app.changes[-1] == ("", {})


async def test_picker_escape_changes_nothing():
    app = BarApp()
    async with app.run_test(size=(80, 24)) as pilot:
        app.bar.choose()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.bar.facets == {}
        assert app.changes == []


async def test_no_groups_means_no_picker():
    app = BarApp(groups=())
    async with app.run_test(size=(80, 10)) as pilot:
        app.bar.choose()
        await pilot.pause()
        assert not isinstance(app.screen, FacetPicker)


async def test_clear_drops_query_and_facets():
    app = BarApp()
    async with app.run_test(size=(80, 10)) as pilot:
        app.bar.query_one(FilterInput).value = "abc"
        app.bar.set_facet("runner", "pytest")
        app.bar.clear()
        await pilot.pause()
        assert app.bar.facets == {} and app.bar.query == ""
        assert app.bar.query_one(Chips).facets == {}
        assert app.changes[-1] == ("", {})


async def test_narrow_bar_fits():
    app = BarApp()
    async with app.run_test(size=(40, 10)) as pilot:
        app.bar.set_count(1234, 5000)
        await pilot.pause()
        assert "1,234 of 5,000" in screen_text(app)
