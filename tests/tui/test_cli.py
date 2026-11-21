import subprocess
import sys
from pathlib import Path

import pytest

import gauntlet.tui.app as tui_app
from gauntlet.harness import cli

SRC = Path(__file__).resolve().parents[2] / "src"


class NoTextual:
    """An import hook that acts as if Textual isn't installed."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "textual" or fullname.startswith("textual."):
            raise ModuleNotFoundError(f"No module named {fullname!r}", name="textual")
        return None


def test_tui_passes_its_options_to_the_viewer(monkeypatch):
    seen = {}

    def fake_run(datasets, runs, *, ascii, theme, workspace):
        seen.update(datasets=datasets, runs=runs, ascii=ascii, theme=theme, workspace=workspace)
        return 0

    monkeypatch.setattr(tui_app, "run", fake_run)
    argv = ["tui", "--datasets", "d", "--run", "a", "--run", "b", "--ascii", "--theme", "gauntlet-light"]
    assert cli.main([*argv, "--workspace", "w"]) == 0
    expected = {
        "datasets": "d",
        "runs": ["a", "b"],
        "ascii": True,
        "theme": "gauntlet-light",
        "workspace": "w",
    }
    assert seen == expected
    assert cli.main(["tui"]) == 0
    assert seen == {"datasets": None, "runs": [], "ascii": False, "theme": None, "workspace": "gauntlet-work"}


def test_tui_without_textual_says_how_to_install_it(monkeypatch, capsys):
    for name in list(sys.modules):
        if name == "textual" or name.startswith(("textual.", "gauntlet.tui.")):
            monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "meta_path", [NoTextual(), *sys.meta_path])
    assert cli.main(["tui"]) == 1
    err = capsys.readouterr().err.strip().splitlines()
    assert err == ['the viewer needs Textual: pip install "gauntlet[tui]"']


@pytest.mark.parametrize("module", ["gauntlet", "gauntlet.harness.cli"])
def test_core_imports_never_load_textual(module):
    code = f"import sys, {module}; print('textual' in sys.modules, 'rich' in sys.modules)"
    out = subprocess.run(
        [sys.executable, "-c", code], env={"PYTHONPATH": str(SRC)}, capture_output=True, text=True, check=True
    )
    assert out.stdout.split()[0] == "False"


def test_cli_help_lists_tui(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "gauntlet tui" in capsys.readouterr().out


def test_run_rejects_unknown_themes_and_missing_folders(tmp_path, capsys):
    assert tui_app.run(theme="nope") == tui_app.EXIT_USAGE
    assert "no theme called nope" in capsys.readouterr().out
    assert tui_app.run(runs=[tmp_path / "missing"]) == tui_app.EXIT_USAGE
    assert "not a folder" in capsys.readouterr().out


def test_run_reports_a_load_failure_in_one_line(tmp_path, monkeypatch, capsys):
    def broken(datasets, runs):
        raise ValueError("results.jsonl line 3 is not JSON")

    monkeypatch.setattr(tui_app, "load_source", broken)
    assert tui_app.run(runs=[tmp_path]) == tui_app.EXIT_ERROR
    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["error: couldn't load the data: ValueError: results.jsonl line 3 is not JSON"]


def test_run_defaults_to_the_datasets_folder_here(tmp_path, monkeypatch):
    (tmp_path / "datasets").mkdir()
    monkeypatch.chdir(tmp_path)
    seen = {}

    def capture(datasets, runs):
        seen.update(datasets=datasets, runs=runs)
        return object()

    monkeypatch.setattr(tui_app, "load_source", capture)
    monkeypatch.setattr(tui_app.GauntletApp, "run", lambda self: None)
    assert tui_app.run(runs=[str(tmp_path)]) == 0
    assert seen == {"datasets": Path("datasets"), "runs": [tmp_path]}
    (tmp_path / "datasets").rmdir()
    assert tui_app.run() == 0
    assert seen["datasets"] is None
