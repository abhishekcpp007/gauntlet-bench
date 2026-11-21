from dataclasses import replace

from gauntlet.tui.app import GauntletApp
from gauntlet.tui.screens.overview import ScoreStrip, headline
from gauntlet.tui.theme import make_look
from gauntlet.tui.widgets import DataGrid, Stat

from .factories import make_source, screen_text

WIDE = (120, 36)
SMALL = (80, 24)


async def open_overview(app: GauntletApp, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()


async def test_headline_numbers():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_overview(app, pilot)
        stats = {s.label: s for s in app.screen.query(Stat)}
        assert set(stats) == {"tasks", "repos", "leak checks", "oracle resolved", "best cheat", "violations"}
        text = screen_text(app)
        assert "✓ 96/96" in text
        assert "✓ 8/8" in text
        assert " 0.00" in text


def test_headline_flags_problems():
    source = make_source()
    overview = source.overview()
    runs = (replace(overview.runs[0], violations=2), overview.runs[1])
    totals = replace(overview.totals, leak_check_failures=1)
    look = make_look({})
    stats = {s.label: s for s in headline(replace(overview, runs=runs, totals=totals), look)}
    assert str(stats["violations"].value).startswith("▲ 2")
    assert str(stats["leak checks"].value).startswith("✗ 95/96")


async def test_tables_list_datasets_and_runs():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_overview(app, pilot)
        datasets = app.screen.query_one("#datasets", DataGrid)
        runs = app.screen.query_one("#runs", DataGrid)
        assert [d.id for d in datasets.rows] == [
            "gauntlet-live-2026-11",
            "gauntlet-live-js-2026-11",
            "gauntlet-lht-2026-11",
        ]
        assert [r.id for r in runs.rows] == ["golden", "shipped:gauntlet-live-2026-11"]
        text = screen_text(app)
        assert "Datasets · 3" in text and "Runs · 2" in text
        assert "2026-09-07 to 2026-10-30" in text
        assert "◌ summary" in text


async def test_score_strip_walks_the_grading_steps_in_order():
    app = GauntletApp(make_source())
    async with app.run_test(size=WIDE) as pilot:
        await open_overview(app, pilot)
        strip = app.screen.query_one(ScoreStrip)
        assert [s.id for s in strip.steps][:3] == ["diff", "scan", "strip"]
        text = screen_text(app)
        assert "How a score is made" in text
        assert "1 Diff → 2 Scan → 3 Strip" in text
        assert "11 Reward" in text


async def test_warnings_show_under_the_numbers():
    app = GauntletApp(make_source(warnings=("results.jsonl line 4: [bad] json",)))
    async with app.run_test(size=WIDE) as pilot:
        await open_overview(app, pilot)
        assert "▲ results.jsonl line 4: [bad] json" in screen_text(app)


async def test_overview_at_80x24_keeps_the_essentials():
    app = GauntletApp(make_source())
    async with app.run_test(size=SMALL) as pilot:
        await open_overview(app, pilot)
        text = screen_text(app)
        assert all(len(line) <= SMALL[0] for line in text.splitlines())
        for words in ("Dataset", "Tasks", "Leak checks", "Run", "Episodes", "Violations", "11 Reward"):
            assert words in text
