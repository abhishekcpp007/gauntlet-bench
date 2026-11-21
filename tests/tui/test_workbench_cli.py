from pathlib import Path

import gauntlet.tui.app as tui_app

from .factories import make_source
from .fakejobs import FakeJobRunner


def test_run_with_a_workspace_starts_the_workbench(tmp_path, monkeypatch):
    runner = FakeJobRunner()
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


def test_the_real_workbench_loads_the_workspace_and_its_runner(tmp_path):
    from gauntlet.tui.jobs import SubprocessJobRunner

    from .sample import SAMPLE_DATASETS

    source, runner, reload = tui_app.load_workbench(SAMPLE_DATASETS, [], tmp_path / "work")
    try:
        assert isinstance(runner, SubprocessJobRunner)
        assert runner.jobs() == () and (tmp_path / "work" / "jobs").is_dir()
        fresh = reload()
        assert fresh is not source and [d.id for d in fresh.datasets()] == [d.id for d in source.datasets()]
    finally:
        runner.close()


def test_a_workspace_inside_datasets_is_refused(tmp_path, capsys):
    inside = tmp_path / "datasets" / "work"
    inside.mkdir(parents=True)
    assert tui_app.run(workspace=inside) == tui_app.EXIT_ERROR
    assert "inside a 'datasets' folder" in capsys.readouterr().out
