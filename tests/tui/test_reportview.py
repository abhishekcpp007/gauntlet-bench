import subprocess
import sys

from gauntlet.tui.widgets.reportview import (
    NO_REPORT,
    Bullet,
    Heading,
    Paragraph,
    ReportTable,
    ReportView,
    parse_report,
)

from .factories import WidgetApp, screen_text
from .sample import SAMPLE_RUN

WIDE = (140, 60)
SMALL = (80, 24)
HOSTILE = "[red]x[/red] \x1b[31mboom"


def real_report(*flags: str) -> list[str]:
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "gauntlet.harness.cli",
            "report",
            "--results",
            str(SAMPLE_RUN / "results.jsonl"),
            *flags,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.splitlines()


def test_it_reads_the_real_report_into_blocks():
    blocks = parse_report(real_report("--cutoff", "2026-10-01"))
    headings = [b.text for b in blocks if isinstance(b, Heading)]
    assert headings == ["SWE: single-PR tasks", "LHT: long-horizon release ranges"]
    tables = [b for b in blocks if isinstance(b, ReportTable)]
    leaderboard = tables[0]
    assert leaderboard.header[:3] == ("Policy", "Resolved", "pass@1")
    assert [row[0] for row in leaderboard.rows] == ["oracle", "noop", "cheater", "cheater:monkeypatch"]
    assert all(not set("".join(row)) <= set("-|: ") for row in leaderboard.rows)
    assert any(isinstance(b, Bullet) and b.text.startswith("oracle:") for b in blocks)
    assert any(isinstance(b, Paragraph) and b.text.startswith("Paired comparisons") for b in blocks)


def test_a_paragraph_runs_on_until_a_blank_line():
    blocks = parse_report(["one", "two", "", "| a | b |", "|---|---|", "| x | 1.0 |", "three"])
    assert blocks == (Paragraph("one two"), ReportTable(("a", "b"), (("x", "1.0"),)), Paragraph("three"))


async def test_the_real_report_draws_as_tables():
    app = WidgetApp(ReportView(parse_report(real_report())))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "|---|" not in text and "| oracle |" not in text
        assert "SWE: single-PR tasks" in text and "Policy" in text and "cheater:monkeypatch" in text
        oracle = next(
            line for line in text.splitlines() if line.strip().startswith("oracle ") and "1.000" in line
        )
        assert oracle.split()[:3] == ["oracle", "1.000", "1.000"]


async def test_cells_are_drawn_literally():
    app = WidgetApp(ReportView((ReportTable(("Policy", "Reward"), ((HOSTILE, "1.0"),)),)))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert "[red]x[/red] ^[[31mboom" in screen_text(app)


async def test_a_report_with_no_table_says_so():
    app = WidgetApp(ReportView(parse_report(["Traceback (most recent call last):"])))
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert NO_REPORT in screen_text(app)


async def test_ascii_mode_draws_ascii_rules():
    app = WidgetApp(ReportView(parse_report(real_report())), ascii=True)
    async with app.run_test(size=WIDE) as pilot:
        await pilot.pause()
        assert "─" not in screen_text(app)


async def test_fits_at_80_by_24():
    app = WidgetApp(ReportView(parse_report(real_report())))
    async with app.run_test(size=SMALL) as pilot:
        await pilot.pause()
        assert all(len(line) <= SMALL[0] for line in screen_text(app).splitlines())
