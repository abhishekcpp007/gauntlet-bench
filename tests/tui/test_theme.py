from textual.color import Color

from gauntlet.tui import theme


def test_two_themes_with_the_default_first():
    names = [t.name for t in theme.THEMES]
    assert names == ["gauntlet-dark", "gauntlet-light"]
    assert theme.DEFAULT_THEME == "gauntlet-dark"
    assert theme.GAUNTLET_DARK.dark and not theme.GAUNTLET_LIGHT.dark


def test_every_mark_has_a_symbol_an_ascii_symbol_and_a_word():
    marks = [
        *theme.VERDICTS.values(),
        *theme.SEVERITIES.values(),
        theme.RESOLVED,
        theme.UNRESOLVED,
        theme.PASSED,
        theme.FAILED,
        theme.LEAK_OK,
        theme.LEAK_FAILED,
        theme.TAMPERED,
        theme.INTACT,
        theme.ERROR,
        theme.SUMMARY_ONLY,
    ]
    for mark in marks:
        assert mark.symbol and mark.word
        assert mark.ascii and mark.ascii.isascii()
    assert set(theme.VERDICTS) == {"clean", "suspicious", "cheating"}
    assert set(theme.SEVERITIES) == {"low", "medium", "high"}


def test_status_tones_keep_their_roles():
    assert theme.VERDICTS["clean"].tone == "good"
    assert theme.VERDICTS["suspicious"].tone == "warn"
    assert theme.VERDICTS["cheating"].tone == "bad"
    assert theme.resolved_mark(True) is theme.RESOLVED
    assert theme.resolved_mark(False).tone == "muted"
    assert theme.leak_mark(False).tone == "bad"
    assert theme.check_mark(False) is theme.FAILED
    assert theme.tamper_mark(True) is theme.TAMPERED


def test_ascii_glyphs_are_ascii():
    glyphs = theme.ASCII_GLYPHS
    for value in (glyphs.crumb, glyphs.dot, glyphs.ellipsis, glyphs.ascending, glyphs.descending):
        assert value.isascii()
    assert all(frame.isascii() for frame in glyphs.spinner)


PALETTE = theme.Palette(
    good="#00ff00", warn="#ffff00", bad="#ff0000", muted="#808080", plain="#ffffff", accent="#0000ff"
)


def test_reward_scale_diverges_from_neutral():
    assert theme.reward_color(1.0, PALETTE) == Color.parse("#00ff00").hex
    assert theme.reward_color(-1.0, PALETTE) == Color.parse("#ff0000").hex
    assert theme.reward_color(0.0, PALETTE) == Color.parse("#808080").hex
    assert theme.reward_color(5.0, PALETTE) == theme.reward_color(1.0, PALETTE)
    half = Color.parse(theme.reward_color(0.5, PALETTE))
    assert half.g > Color.parse("#808080").g and half.r < Color.parse("#808080").r


def test_reward_scale_survives_colours_it_cannot_blend():
    palette = theme.Palette(
        good="ansi_green", warn="ansi_yellow", bad="ansi_red", muted="ansi_default", plain="x", accent="y"
    )
    assert theme.reward_color(0.4, palette) == "ansi_green"
    assert theme.reward_color(0.0, palette) == "ansi_default"


def test_look_renders_marks_and_rewards():
    look = theme.Look(PALETTE, theme.UNICODE_GLYPHS)
    text = look.mark(theme.VERDICTS["cheating"])
    assert text.plain == "● cheating"
    assert text.style.color is not None
    assert look.mark(theme.RESOLVED, word=False).plain == "✓"
    assert look.reward(-1.0).plain == "-1.00"
    assert look.reward(None).plain == "-"
    ascii_look = theme.Look(PALETTE, theme.ASCII_GLYPHS, ascii=True)
    assert ascii_look.mark(theme.VERDICTS["suspicious"]).plain == "^ suspicious"


def test_palette_reads_theme_variables():
    palette = theme.Palette.from_variables(
        {"text-success": "#111111", "foreground-muted": "#222222", "text-primary": "#333333"}
    )
    assert palette.good == "#111111" and palette.muted == "#222222" and palette.accent == "#333333"
    look = theme.make_look({}, ascii=True)
    assert look.ascii and look.glyphs is theme.ASCII_GLYPHS


def test_solid_color_flattens_see_through_and_keeps_ansi():
    variables = {"background": "#000000", "muted": "#ffffff80", "ansi": "ansi_green", "bad": "nope"}
    assert theme.solid_color(variables, "muted") == Color.parse("#808080").hex
    assert theme.solid_color(variables, "ansi") == "color(2)"
    assert theme.solid_color(variables, "bad") is None
    assert theme.solid_color(variables, "missing") is None
