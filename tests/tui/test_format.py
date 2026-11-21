import pytest
from rich.text import Text

from gauntlet.tui import format as fmt


@pytest.mark.parametrize(
    ("value", "shown"),
    [(0.97, "+0.97"), (-1.0, "-1.00"), (0.0, " 0.00"), (-0.0, " 0.00"), (0.004, " 0.00"), (1.0, "+1.00")],
)
def test_rewards_carry_a_sign_and_two_decimals(value, shown):
    assert fmt.reward(value) == shown


def test_percent_count_and_ratio():
    assert fmt.percent(0.973) == "97%"
    assert fmt.percent(0.973, digits=1) == "97.3%"
    assert fmt.percent(None) == fmt.MISSING
    assert fmt.count(5000) == "5,000"
    assert fmt.count(None) == fmt.MISSING
    assert fmt.ratio(5, 7) == "5/7"
    assert fmt.ratio(1200, 1500) == "1,200/1,500"


def test_plural():
    assert fmt.plural(1, "task") == "1 task"
    assert fmt.plural(3, "task") == "3 tasks"
    assert fmt.plural(0, "run") == "0 runs"
    assert fmt.plural(2, "policy", "policies") == "2 policies"
    assert fmt.plural(1234, "episode") == "1,234 episodes"


@pytest.mark.parametrize(
    ("seconds", "shown"),
    [(0.42, "0.4 s"), (4.2, "4.2 s"), (59.94, "59.9 s"), (185, "3 m 05 s"), (3725, "1 h 02 m"), (None, "-")],
)
def test_durations_read_like_a_person_wrote_them(seconds, shown):
    assert fmt.duration(seconds) == shown


def test_dates_and_ranges():
    assert fmt.date("2026-10-06T11:01:26Z") == "2026-10-06"
    assert fmt.date("2025-10-15T21:12:12+03:00") == "2025-10-15"
    assert fmt.date(None) == fmt.MISSING
    assert fmt.date("not a date") == fmt.MISSING
    assert fmt.date(0) == "1970-01-01"
    assert fmt.date_time("2026-10-06T11:01:26Z") == "2026-10-06 11:01"
    assert fmt.date_range("2026-09-07T09:17:17Z", "2026-10-30T17:05:19Z") == "2026-09-07 to 2026-10-30"
    assert fmt.date_range("2026-09-07T01:00:00Z", "2026-09-07T23:00:00Z") == "2026-09-07"
    assert fmt.date_range(None, "2026-09-07") == "2026-09-07"
    assert fmt.date_range("2026-09-07", None) == "2026-09-07"
    assert fmt.date_range(None, None) == fmt.MISSING


def test_middle_ellipsis_keeps_both_ends():
    iid = "more-itertools__more-itertools-1260"
    assert fmt.middle(iid, 100) == iid
    cut = fmt.middle(iid, 15)
    assert len(cut) == 15 and cut.startswith("more-it") and cut.endswith("1260") and fmt.ELLIPSIS in cut
    assert fmt.middle(iid, 12, "...") == "more-...1260"
    assert fmt.middle(iid, 1) == "m"


def test_visible_shows_control_characters_in_caret_form():
    assert fmt.visible("a\x1b[31mb") == "a^[[31mb"
    assert fmt.visible("x\x00y\x7f") == "x^@y^?"
    assert fmt.visible("\x9b") == "\\x9b"
    assert fmt.visible("keep\n\ttabs") == "keep\n\ttabs"


def test_safe_text_is_literal():
    text = fmt.safe_text("[red]boom[/red] \x1b[2J")
    assert isinstance(text, Text)
    assert text.plain == "[red]boom[/red] ^[[2J"
    assert text.spans == []
    assert fmt.safe_text(None).plain == ""
    assert fmt.safe_text("a\n  b", single_line=True).plain == "a b"
    assert fmt.safe_text("\tx").plain == "    x"
