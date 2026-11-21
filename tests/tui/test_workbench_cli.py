from pathlib import Path

import gauntlet.tui.app as tui_app
from gauntlet.harness import cli

from .factories import make_source
from .workfakes import ScriptedRunner


def test_tui_passes_the_workspace_and_defaults_it(monkeypatch):
    seen = {}

    def fake_run(datasets, runs, *, ascii, theme, workspace):
        seen.update(workspace=workspace)
        return 0

    monkeypatch.setattr(tui_app, "run", fake_run)
    assert cli.main(["tui", "--workspace", "w"]) == 0
    assert seen == {"workspace": "w"}
    assert cli.main(["tui"]) == 0
    assert seen == {"workspace": "gauntlet-work"}


def test_run_with_a_workspace_starts_the_workbench(tmp_path, monkeypatch):
    runner = ScriptedRunner()
    started = {}

    def load(datasets, runs, workspace):
        started.update(workspace=workspace)
        return make_source(), runner, make_source

    def capture(app):
        started.update(jobs=app.jobs, reload=app.reload_source)

    monkeypatch.setattr(tui_app, "load_workbench", load)
    monkeypatch.setattr(tui_app.GauntletApp, "run", capture)
    assert tui_app.run(runs=[tmp_path], workspace=tmp_path / "work") == 0
    assert started == {"workspace": tmp_path / "work", "jobs": runner, "reload": make_source}


def test_a_workspace_that_is_a_file_is_refused(tmp_path, capsys):
    file = tmp_path / "work"
    file.write_text("")
    assert tui_app.run(workspace=file) == tui_app.EXIT_USAGE
    assert f"not a folder: {file}" in capsys.readouterr().out


def test_a_workbench_that_cant_start_gets_one_line(tmp_path, monkeypatch, capsys):
    def broken(datasets, runs, workspace):
        raise PermissionError("can't write gauntlet-work")

    monkeypatch.setattr(tui_app, "load_workbench", broken)
    assert tui_app.run(workspace=Path(tmp_path)) == tui_app.EXIT_ERROR
    assert (
        capsys.readouterr().out.strip()
        == "error: couldn't load the data: PermissionError: can't write gauntlet-work"
    )
