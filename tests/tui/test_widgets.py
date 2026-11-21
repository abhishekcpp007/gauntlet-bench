import threading

from rich.style import Style
from rich.text import Text

from gauntlet.tui.models import NotFound
from gauntlet.tui.theme import LEAK_FAILED, VERDICTS
from gauntlet.tui.widgets import (
    CheckItem,
    Checklist,
    CopyRequested,
    Deferred,
    Empty,
    EmptyState,
    ErrorState,
    Fact,
    Facts,
    Loading,
    RewardText,
    Stat,
    StatusBadge,
    describe_error,
)
from gauntlet.tui.widgets.chrome import Destination, NavBar, TopBar
from gauntlet.tui.widgets.definitions import Definition, Definitions

from .factories import WidgetApp, screen_text


async def test_status_badges_show_symbol_and_word():
    app = WidgetApp(
        StatusBadge.verdict("cheating"),
        StatusBadge.resolved(False),
        StatusBadge.severity("medium"),
        StatusBadge.leak_check(True),
    )
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        for shown in ("● cheating", "✗ not resolved", "▲ medium", "✓ ok"):
            assert shown in text


async def test_status_badges_in_ascii():
    app = WidgetApp(StatusBadge.verdict("suspicious"), StatusBadge(VERDICTS["clean"]), ascii=True)
    async with app.run_test(size=(40, 4)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "^ suspicious" in text and "+ clean" in text
        assert text.isascii()


async def test_reward_text_updates():
    reward = RewardText(0.97)
    app = WidgetApp(reward)
    async with app.run_test(size=(20, 3)) as pilot:
        await pilot.pause()
        assert "+0.97" in screen_text(app)
        reward.value = -1.0
        await pilot.pause()
        assert "-1.00" in screen_text(app)
        reward.value = None
        await pilot.pause()
        assert "-" in screen_text(app)


class FactsApp(WidgetApp):
    def __init__(self, facts: Facts) -> None:
        super().__init__(facts)
        self.copied: list[tuple[str, str]] = []

    def on_copy_requested(self, event: CopyRequested) -> None:
        self.copied.append((event.text, event.what))


async def test_facts_move_and_copy():
    facts = Facts(
        [
            Fact("Image", "gauntlet-harness-env:8b04a9c8ff22041c"),
            Fact("Reward", Text("+0.97"), copy="0.97"),
            Fact("Statement", "[red]boom[/red]\x1b[2J"),
        ]
    )
    app = FactsApp(facts)
    async with app.run_test(size=(80, 6)) as pilot:
        facts.focus()
        await pilot.press("c")
        await pilot.press("j", "c")
        await pilot.press("down", "down", "k", "up", "up", "c")
        assert app.copied == [
            ("gauntlet-harness-env:8b04a9c8ff22041c", "image"),
            ("0.97", "reward"),
            ("gauntlet-harness-env:8b04a9c8ff22041c", "image"),
        ]
        text = screen_text(app)
        assert "Image      gauntlet-harness-env" in text
        assert "[red]boom[/red]^[[2J" in text
        facts.set_facts([Fact("Only", "one")])
        await pilot.pause()
        assert facts.cursor == 0 and facts.current == Fact("Only", "one")


async def test_checklist_marks_each_item():
    items = [CheckItem("network", True, "BLOCKED"), CheckItem("gold on disk", False, "1 gold line readable")]
    checklist = Checklist(items, failed=LEAK_FAILED)
    app = WidgetApp(checklist)
    async with app.run_test(size=(60, 8)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "✓ network  pass" in text
        assert "✗ gold on disk  failed" in text
        assert "1 gold line readable" in text
        assert checklist.passing == 1


async def test_states():
    app = WidgetApp(
        EmptyState(Empty("No runs loaded.", "Add one with --run DIR.")),
        ErrorState("Couldn't load the run", "LoadFailed: disk [b]gone[/b]"),
        Loading("the trajectory"),
    )
    async with app.run_test(size=(60, 20)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "No runs loaded." in text and "Add one with --run DIR." in text
        assert "! Couldn't load the run" in text and "disk [b]gone[/b]" in text
        assert "Loading the trajectory…" in text


def test_describe_error():
    assert describe_error(NotFound("tomli-1")) == "Nothing called tomli-1 was loaded."
    assert describe_error(OSError("disk gone")) == "OSError: disk gone"
    assert describe_error(ValueError()) == "ValueError"


async def test_stat_definitions_and_chrome_render():
    top = TopBar()
    nav = NavBar((Destination("1", "Overview", "a"), Destination("2", "Tasks", "b")), "b")
    app = WidgetApp(
        top,
        nav,
        Stat("147", "tasks", note="in 3 sets"),
        Definitions([Definition("network", "The network is blocked.")], numbered=True),
    )
    async with app.run_test(size=(60, 10)) as pilot:
        top.show(("Runs", "golden", "hukkin__tomli-318__cheater:ghost__0"), "147 tasks · 4 runs")
        await pilot.pause()
        text = screen_text(app)
        lines = text.splitlines()
        assert lines[0].startswith(" GAUNTLET  Runs › golden › ")
        assert lines[0].rstrip().endswith("147 tasks · 4 runs")
        assert "…" in lines[0]
        assert "1 Overview" in lines[1] and "2 Tasks" in lines[1]
        assert "147 in 3 sets" in text and "tasks" in text
        assert "1  network  The network is blocked." in text


class Gate:
    def __init__(self) -> None:
        self.release = threading.Event()

    def fetch(self) -> str:
        self.release.wait(timeout=5)
        return "loaded value"


async def test_deferred_shows_loading_then_content():
    gate = Gate()
    pane = Deferred(gate.fetch, lambda value: [Stat(value, "label")], what="the thing", lazy=False)
    app = WidgetApp(pane)
    async with app.run_test(size=(60, 6)) as pilot:
        await pilot.pause()
        assert "Loading the thing" in screen_text(app)
        gate.release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "loaded value" in screen_text(app)


async def test_deferred_error_keeps_the_app_alive():
    def boom() -> str:
        raise OSError("can't read rl/x.json")

    def bad_build(_value: str) -> list:
        raise KeyError("missing")

    app = WidgetApp(
        Deferred(boom, lambda value: [], what="the reward", lazy=False),
        Deferred(lambda: "x", bad_build, what="the rubric", lazy=False),
    )
    async with app.run_test(size=(60, 12)) as pilot:
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = screen_text(app)
        assert "Couldn't load the reward" in text and "OSError: can't read rl/x.json" in text
        assert "Couldn't load the rubric" in text
        assert app.is_running


async def test_lazy_deferred_waits_until_shown():
    calls: list[int] = []

    def fetch() -> str:
        calls.append(1)
        return "ok"

    pane = Deferred(fetch, lambda value: [Stat(value, "x")], what="tests")
    pane.display = False
    app = WidgetApp(pane)
    async with app.run_test(size=(40, 6)) as pilot:
        await pilot.pause()
        assert calls == []
        pane.display = True
        await pilot.pause()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert calls == [1]
        pane.load()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert calls == [1, 1]


async def test_checklist_bolds_only_the_label():
    checklist = Checklist([CheckItem("network", False, "not blocked")])
    app = WidgetApp(checklist)
    async with app.run_test(size=(60, 4)) as pilot:
        await pilot.pause()
        body = checklist.render().columns[1]._cells[0]
        assert body.style == ""
        styles = [(body.plain[s.start : s.end], s.style) for s in body.spans]
        bold = [
            part for part, style in styles if (Style.parse(style) if isinstance(style, str) else style).bold
        ]
        assert bold == ["network"]
