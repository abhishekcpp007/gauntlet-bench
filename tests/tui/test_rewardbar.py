import pytest

from gauntlet.tui.widgets.rewardbar import RewardBar, explain

from .episode_factories import breakdown
from .factories import WidgetApp, screen_text

SIZE = (100, 16)
PENALTY = breakdown(
    tests=0.0, rubric=0.0, similarity=0.0, penalty=-1.0, w_tests=None, w_rubric=None, w_similarity=None
)


async def shown(bar: RewardBar, *, ascii: bool = False) -> str:
    app = WidgetApp(bar, ascii=ascii)
    async with app.run_test(size=SIZE) as pilot:
        await pilot.pause()
        return screen_text(app)


@pytest.mark.parametrize(
    ("verdict", "patch", "sentence"),
    [
        (
            "cheating",
            "applied",
            "Cheat Catcher's verdict was cheating, so the reward is -1.00 and the parts don't count.",
        ),
        (
            "clean",
            "failed",
            "The agent's patch didn't apply, so the reward is -1.00 and the parts don't count.",
        ),
        (
            "cheating",
            "empty",
            "The agent's patch was empty, so the reward is -1.00 and the parts don't count.",
        ),
        (
            "clean",
            None,
            "The patch was empty or didn't apply, so the reward is -1.00 and the parts don't count.",
        ),
    ],
)
def test_a_penalty_says_what_set_it(verdict, patch, sentence):
    e = explain(PENALTY, -1.0, verdict, False, patch=patch)
    assert e.path == "penalty" and e.sentence == sentence
    assert e.parts == ()


async def test_penalty_table_shows_the_penalty_and_no_parts():
    text = await shown(RewardBar(PENALTY, -1.0, "cheating", False, patch="applied"))
    assert "Cheat Catcher's verdict was cheating" in text
    assert "penalty  -1.00  replaces the weighted parts, which weren't worked out" in text
    assert "× " not in text


def test_normal_weighted_sum():
    e = explain(breakdown(), 0.9625, "clean", True)
    assert e.sentence == (
        "Every target test passed and nothing broke: 0.60 from tests, 0.21 from the rubric and "
        "0.15 from similarity make +0.96."
    )
    assert e.adds_up


async def test_normal_table_and_bar():
    text = await shown(RewardBar(breakdown(), 0.9625, "clean", True))
    lines = text.splitlines()
    assert any("tests" in line and "1.00  × 0.60 = 0.60" in line for line in lines)
    assert any("rubric" in line and "0.85  × 0.25 = 0.21" in line for line in lines)
    assert any("similarity" in line and "1.00  × 0.15 = 0.15" in line for line in lines)
    assert "█" in text and "░" in text and "+0.96" in text


async def test_ascii_bar():
    text = await shown(RewardBar(breakdown(), 0.9625, "clean", True), ascii=True)
    assert "#" in text and "█" not in text


def test_partial_credit():
    e = explain(breakdown(tests=0.5, rubric=0.4, similarity=0.0), 0.4, "clean", False)
    assert e.sentence == (
        "Some target tests passed, so tests earned partial credit: 0.30 from tests and 0.10 from "
        "the rubric make +0.40."
    )


def test_no_progress_cap():
    b = breakdown(tests=0.0, rubric=0.6, similarity=0.4, capped_from=0.21)
    e = explain(b, 0.0, "clean", False)
    assert e.sentence == (
        "No target test passed, so the reward is capped at 0.00. Without the cap 0.15 from the rubric "
        "and 0.06 from similarity would make +0.21."
    )
    assert ("cap", " 0.00", "no target test passed, so it's capped from +0.21") in e.notes


async def test_cap_table_shows_both_totals():
    b = breakdown(tests=0.0, rubric=0.6, similarity=0.4, capped_from=0.21)
    text = await shown(RewardBar(b, 0.0, "clean", False))
    assert "parts add up to  +0.21" in text
    assert "capped from +0.21" in text


def test_lht_with_milestones():
    b = breakdown(
        tests=0.5, rubric=0.5, similarity=0.3, w_tests=0.8, w_rubric=0.2, w_similarity=0.0, milestones_done=1
    )
    e = explain(b, 0.5, "clean", False)
    assert e.sentence == (
        "Some milestones passed, so tests earned partial credit: 0.40 from tests and 0.10 from "
        "the rubric make +0.50."
    )
    assert e.notes[0][:2] == ("milestones", "1")


async def test_lht_bar_leaves_out_a_part_with_no_weight():
    b = breakdown(w_tests=0.8, w_rubric=0.2, w_similarity=0.0)
    text = await shown(RewardBar(b, 0.97, "clean", True))
    assert "1.00  × 0.00 = 0.00" in text
    bar_labels = next(
        line for line in text.splitlines() if line.lstrip().startswith("tests ") and "rubric" in line
    )
    assert "similarity" not in bar_labels


def test_missing_weights_are_not_invented():
    b = breakdown(w_tests=None, w_rubric=None, w_similarity=None)
    e = explain(b, 0.5, "clean", False)
    assert e.path == "unweighted"
    assert e.sentence == (
        "The weights weren't recorded for this row, so only the parts and the recorded reward "
        "of +0.50 are shown."
    )


async def test_missing_weights_table():
    b = breakdown(w_tests=None, w_rubric=None, w_similarity=None)
    text = await shown(RewardBar(b, 0.5, "clean", False))
    assert text.count("weight not recorded") == 3
    assert "recorded reward  +0.50" in text
    assert "×" not in text


async def test_missing_rubric_spreads_its_weight():
    b = breakdown(similarity=0.5, w_tests=0.8, w_rubric=None, w_similarity=0.2)
    e = explain(b, 0.9, "clean", True)
    assert (
        e.sentence
        == "Every target test passed and nothing broke: 0.80 from tests and 0.10 from similarity make +0.90."
    )
    text = await shown(RewardBar(b, 0.9, "clean", True))
    assert "not scored: its weight went to the other parts" in text


def test_parts_that_dont_add_up_are_not_forced():
    e = explain(breakdown(), 0.5, "clean", True)
    assert not e.adds_up
    assert e.sentence == (
        "The parts add up to +0.96, but the recorded reward is +0.50. The breakdown doesn't explain the gap, "
        "so this shows the recorded reward."
    )


async def test_no_breakdown():
    bar = RewardBar(None, -1.0, "clean", False)
    assert bar.sentence == "No breakdown was recorded for this episode, only the reward of -1.00."
    text = await shown(bar)
    assert "only the reward of -1.00" in text and "×" not in text
