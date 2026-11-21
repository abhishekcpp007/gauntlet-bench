import time

from gauntlet.tui.models import Matrix as MatrixData
from gauntlet.tui.models import MatrixCell, MatrixTask
from gauntlet.tui.widgets import CopyRequested
from gauntlet.tui.widgets.matrix import CellStatus, Legend, Matrix, MatrixTable, short_policy

from .factories import WidgetApp, screen_text

POLICIES = ("oracle", "noop", "cheater", "cheater:canary-aware")
TASKS = ("hukkin__tomli-318", "mahmoud__boltons-471")
BIG_TASKS = 69
BIG_POLICIES = 11
FAST_SECONDS = 2.0


def cell(task: str, policy: str, reward: float, **kwargs) -> MatrixCell:
    values = {"resolved": False, "verdict": "clean", "tampered": False} | kwargs
    return MatrixCell(f"{task}__{policy}__0", reward, **values)


def sample(*, missing: bool = True) -> MatrixData:
    rows = []
    for task in TASKS:
        rows.append(
            (
                cell(task, "oracle", 1.0, resolved=True),
                cell(task, "noop", -1.0),
                cell(task, "cheater", -1.0, verdict="cheating", tampered=True),
                None if missing and task == TASKS[1] else cell(task, POLICIES[3], 0.0, verdict="suspicious"),
            )
        )
    tasks = tuple(MatrixTask(t, t.split("__")[0], "swe") for t in TASKS)
    return MatrixData(POLICIES, tasks, tuple(rows))


def big() -> MatrixData:
    policies = tuple(f"cheater:policy-{i}" for i in range(BIG_POLICIES))
    tasks = tuple(MatrixTask(f"owner__repository-name-{i}", "owner", "swe") for i in range(BIG_TASKS))
    cells = tuple(tuple(cell(t.instance_id, p, -1.0) for p in policies) for t in tasks)
    return MatrixData(policies, tasks, cells)


class MatrixApp(WidgetApp):
    def __init__(self, data: MatrixData, *, ascii: bool = False) -> None:
        self.matrix = Matrix(data)
        super().__init__(self.matrix, ascii=ascii)
        self.opened: list[str] = []
        self.copied: list[tuple[str, str]] = []

    def on_matrix_opened(self, event: Matrix.Opened) -> None:
        self.opened.append(event.episode_id)

    def on_copy_requested(self, event: CopyRequested) -> None:
        self.copied.append((event.text, event.what))


def status_text(app: MatrixApp) -> str:
    return str(app.matrix.query_one(CellStatus).render())


def test_short_policy_keeps_the_name_after_the_colon():
    assert short_policy("oracle") == "oracle"
    assert short_policy("cheater:ghost") == "ghost"
    assert short_policy("cheater:canary-aware") == "canary-a…"
    assert short_policy("cheater:canary-aware", "...") == "canary..."


async def test_cells_show_signed_rewards_and_marks():
    app = MatrixApp(sample())
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "Task" in text and "oracle" in text and "canary-a…" in text
        first = next(line for line in text.splitlines() if TASKS[0] in line)
        assert "+1.00 ✓" in first and "-1.00 ●✗" in first and " 0.00 ▲" in first
        second = next(line for line in text.splitlines() if TASKS[1] in line)
        assert second.rstrip().endswith("·")


async def test_legend_and_status_line_name_the_focused_cell_in_full():
    app = MatrixApp(sample())
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        legend = str(app.matrix.query_one(Legend).render())
        for words in ("✓ resolved", "● cheating", "▲ suspicious", "✗ tampered", "· not played", "-1.00"):
            assert words in legend
        assert status_text(app).startswith(f"{TASKS[0]}  ·  oracle  ·  +1.00  ·  ✓ resolved  ·  ✓ clean")
        await pilot.press("l", "l", "l")
        assert "cheater:canary-aware" in status_text(app)
        assert "▲ suspicious" in status_text(app)
        await pilot.press("j")
        assert status_text(app).endswith("· not played")


async def test_legend_leaves_out_not_played_when_every_pair_was_played():
    app = MatrixApp(sample(missing=False))
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        assert "not played" not in str(app.matrix.query_one(Legend).render())


async def test_cursor_moves_with_arrows_and_hjkl_and_stops_at_the_edges():
    app = MatrixApp(sample())
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.focused, MatrixTable)
        assert app.matrix.coordinate == (0, 0)
        await pilot.press("h", "left", "k", "up")
        assert app.matrix.coordinate == (0, 0)
        await pilot.press("l", "right")
        assert app.matrix.coordinate == (0, 2)
        await pilot.press("l", "l", "l")
        assert app.matrix.coordinate == (0, 3)
        await pilot.press("j", "down", "j")
        assert app.matrix.coordinate == (1, 3)
        await pilot.press("h")
        assert app.matrix.coordinate == (1, 2)


async def test_enter_posts_the_episode_id_and_c_copies_it():
    app = MatrixApp(sample())
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        await pilot.press("l", "l", "enter")
        assert app.opened == [f"{TASKS[0]}__cheater__0"]
        await pilot.press("c")
        assert app.copied == [(f"{TASKS[0]}__cheater__0", "episode id")]


async def test_a_missing_cell_opens_and_copies_nothing():
    app = MatrixApp(sample())
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        await pilot.press("j", "l", "l", "l", "enter", "c")
        assert app.matrix.current is None
        assert app.opened == [] and app.copied == []


async def test_ascii_symbols():
    app = MatrixApp(sample(), ascii=True)
    async with app.run_test(size=(120, 24)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "+1.00 +" in text and "-1.00 *x" in text and " 0.00 ^" in text
        assert "canary..." in text
        assert not any(ch in text for ch in "✓●✗▲·…")


async def test_a_full_run_stays_fast_and_fits_80x24():
    data = big()
    app = MatrixApp(data)
    async with app.run_test(size=(80, 24)) as pilot:
        started = time.perf_counter()
        await pilot.pause()
        assert time.perf_counter() - started < FAST_SECONDS
        assert app.matrix.table.row_count == BIG_TASKS
        assert len(app.matrix.table.columns) == BIG_POLICIES + 1
        text = screen_text(app)
        assert all(len(line) <= 80 for line in text.splitlines())
        await pilot.press("G")
        assert app.matrix.coordinate == (BIG_TASKS - 1, 0)
        for _ in range(BIG_POLICIES + 2):
            await pilot.press("l")
        assert app.matrix.coordinate == (BIG_TASKS - 1, BIG_POLICIES - 1)
        assert "cheater:policy-10" in status_text(app)
        assert "cheater:policy-10" in screen_text(app)


async def test_task_column_stays_put_while_policies_scroll():
    app = MatrixApp(big())
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        for _ in range(BIG_POLICIES):
            await pilot.press("l")
        assert app.matrix.table.scroll_x > 0
        assert "owner__repository-name-0" in screen_text(app)
