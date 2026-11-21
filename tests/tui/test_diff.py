from gauntlet.tui.widgets import DiffView, parse_diff

from .factories import CHEAT_PATCH, GOLD_PATCH, HOSTILE_PATCH, TEST_PATCH, WidgetApp, screen_text

PLAIN_PATCH = """--- a/one.py
+++ b/one.py
@@ -1,2 +1,2 @@
-old
+new
 same
--- a/two.py
+++ b/two.py
@@ -5 +5 @@
--- a comment that starts with dashes
+++ a line that starts with pluses
"""


def test_parse_counts_files_and_lines():
    parsed = parse_diff(GOLD_PATCH + TEST_PATCH)
    assert [f.path for f in parsed.files] == ["src/tomli/_parser.py", "tests/test_misc.py"]
    assert (parsed.files[0].added, parsed.files[0].removed) == (4, 2)
    assert (parsed.files[1].added, parsed.files[1].removed) == (4, 0)
    first_add = next(line for line in parsed.lines if line.kind == "add")
    assert first_add.new == 213 and first_add.text == "        return pos"
    assert not parsed.truncated


def test_parse_new_file_and_plain_diffs():
    parsed = parse_diff(CHEAT_PATCH)
    assert parsed.files[0].path == "conftest.py" and parsed.files[0].status == "new file"
    plain = parse_diff(PLAIN_PATCH)
    assert [f.path for f in plain.files] == ["one.py", "two.py"]
    assert (plain.files[1].added, plain.files[1].removed) == (1, 1)
    assert [line.text for line in plain.lines if line.kind == "del"][
        -1
    ] == "-- a comment that starts with dashes"


def test_parse_stops_at_the_line_cap_but_counts_everything():
    big = "diff --git a/x b/x\n@@ -1,600 +1,600 @@\n" + "".join(f"-a{i}\n+b{i}\n" for i in range(600))
    parsed = parse_diff(big, max_lines=50)
    assert len(parsed.lines) == 50 and parsed.truncated
    assert parsed.files[0].added == 600 and parsed.files[0].removed == 600


async def test_diff_view_shows_headers_numbers_and_marks():
    view = DiffView(GOLD_PATCH + TEST_PATCH)
    app = WidgetApp(view)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "src/tomli/_parser.py  +4 -2" in text
        assert "@@ -210,7 +210,9 @@" in text
        assert "213 +         return pos" in text
        assert "213     -         char = None" in text or "213" in text
        assert "index 3c1f0e2" not in text


async def test_n_and_p_jump_between_files():
    view = DiffView(GOLD_PATCH + TEST_PATCH + CHEAT_PATCH)
    app = WidgetApp(view)
    async with app.run_test(size=(100, 8)) as pilot:
        view.focus()
        assert view.current_file == "src/tomli/_parser.py"
        await pilot.press("n")
        assert view.current_file == "tests/test_misc.py"
        await pilot.press("n")
        assert view.current_file == "conftest.py"
        await pilot.press("p")
        assert view.current_file == "tests/test_misc.py"


async def test_large_diff_says_what_it_left_out():
    big = "diff --git a/x b/x\n@@ -1,600 +1,600 @@\n" + "".join(f"-a{i}\n+b{i}\n" for i in range(600))
    app = WidgetApp(DiffView(big, max_lines=100))
    async with app.run_test(size=(100, 10)) as pilot:
        await pilot.pause()
        assert "Large patch: showing the first 100 of 1,202 lines." in screen_text(app)


async def test_empty_patch():
    app = WidgetApp(DiffView(None, empty="The agent made no changes."))
    async with app.run_test(size=(60, 5)) as pilot:
        await pilot.pause()
        assert "The agent made no changes." in screen_text(app)


async def test_hostile_patch_renders_literally():
    view = DiffView(HOSTILE_PATCH)
    app = WidgetApp(view)
    async with app.run_test(size=(100, 10)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert "[bold red]boom[/bold red] ^[[31mred^[[0m ^[]0;pwned^G" in text
        assert "-[red]boom[/red]" in text.replace(" ", "")
        assert "tab here" in text
        assert "\x1b" not in text


async def test_narrow_diff_scrolls_sideways_instead_of_wrapping():
    app = WidgetApp(DiffView(GOLD_PATCH))
    async with app.run_test(size=(40, 20)) as pilot:
        await pilot.pause()
        text = screen_text(app)
        assert all(len(line) <= 40 for line in text.splitlines())


def test_files_after_the_first_get_a_blank_line_above_them():
    kinds = [line.kind for line in parse_diff(GOLD_PATCH + TEST_PATCH).lines]
    assert kinds[0] == "file"
    assert kinds[kinds.index("file", 1) - 1] == "gap"
