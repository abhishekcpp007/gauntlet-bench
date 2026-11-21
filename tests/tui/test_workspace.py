from datetime import datetime

import pytest

from gauntlet.tui.workspace import SLUG_MAX, Workspace, WorkspaceError, check_name, slugify

NOON = datetime(2026, 11, 22, 12, 0, 5)


def fixed() -> datetime:
    return NOON


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "work", clock=fixed)


def test_folders_are_made_on_demand(ws):
    assert not ws.root.exists()
    assert ws.tasks_dir("a").is_dir()
    assert ws.run_dir("b").is_dir()
    assert ws.job_dir("20261122-120005-001").is_dir()
    assert ws.reports_dir().is_dir()
    assert ws.path_for("tasks", "a") == ws.root / "tasks" / "a"
    assert not ws.path_for("runs", "never").exists()


def test_new_names_are_readable_sortable_and_unique(ws):
    first = ws.new_name("tasks", "Pallets/Click!")
    assert first == "pallets-click-20261122-120005"
    assert ws.new_name("tasks", "Pallets/Click!") == f"{first}-2"
    assert ws.new_name("runs", "Pallets/Click!") == first
    ws.tasks_dir("other-20261122-120005")
    assert ws.new_name("tasks", "other") == "other-20261122-120005-2"
    (ws.reports_dir() / "rep-20261122-120005.html").write_text("")
    assert ws.new_name("reports", "rep") == "rep-20261122-120005-2"


def test_slugs():
    assert slugify("  ") == "work"
    assert slugify("A" * (SLUG_MAX * 2)) == "a" * SLUG_MAX
    assert slugify("x--y__z") == "x-y-z"


@pytest.mark.parametrize("bad", ["", "..", ".hidden", "-flag", "a/b", "a b", "a\x00"])
def test_bad_names_are_refused(ws, bad):
    with pytest.raises(WorkspaceError):
        check_name(bad)
    with pytest.raises(WorkspaceError):
        ws.tasks_dir(bad)


def test_listings_are_sorted_and_skip_files(ws):
    assert ws.task_sets() == () and ws.runs() == ()
    ws.tasks_dir("b")
    ws.tasks_dir("a")
    (ws.root / "tasks" / "note.txt").write_text("")
    ws.run_dir("r")
    assert [p.name for p in ws.task_sets()] == ["a", "b"]
    assert [p.name for p in ws.runs()] == ["r"]


def test_paths_outside_are_refused_symlinks_included(ws, tmp_path):
    ws.root.mkdir()
    assert ws.inside(ws.root / "tasks" / "x") == ws.root / "tasks" / "x"
    assert ws.contains(ws.root)
    with pytest.raises(WorkspaceError, match="outside"):
        ws.inside(ws.root / ".." / "elsewhere")
    outside = tmp_path / "outside"
    outside.mkdir()
    (ws.root / "tasks").mkdir()
    (ws.root / "tasks" / "sneaky").symlink_to(outside)
    assert not ws.contains(ws.root / "tasks" / "sneaky")
    with pytest.raises(WorkspaceError):
        ws.tasks_dir("sneaky")


def test_the_root_resolves_symlinks(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "link").symlink_to(real)
    assert Workspace(tmp_path / "link").root == real.resolve()


def test_refuses_to_live_in_a_datasets_folder(tmp_path):
    with pytest.raises(WorkspaceError, match="datasets"):
        Workspace(tmp_path / "datasets" / "work")
    (tmp_path / "datasets").mkdir()
    (tmp_path / "alias").symlink_to(tmp_path / "datasets")
    with pytest.raises(WorkspaceError, match="datasets"):
        Workspace(tmp_path / "alias")
    assert Workspace(tmp_path / "datasets-work").root.name == "datasets-work"


def test_refuses_a_file(tmp_path):
    (tmp_path / "f").write_text("")
    with pytest.raises(WorkspaceError, match="file"):
        Workspace(tmp_path / "f")
