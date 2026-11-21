import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

import gauntlet
from gauntlet.tui import store as store_module
from gauntlet.tui.models import DataSource
from gauntlet.tui.store import Store

from .sample import REPO_DATASETS

SHIPPED_EPISODES = {
    "shipped-live-2026-11": 159,
    "shipped-live-js-2026-11": 759,
    "shipped-lht-2026-11": 275,
}
SHIPPED_TASKS = 147
SHIPPED_REPOS = 26
SHIPPED_SETS = 3


def _protocol_methods() -> list[str]:
    return [
        name
        for name, value in vars(DataSource).items()
        if not name.startswith("_") and inspect.isfunction(value)
    ]


@pytest.mark.parametrize("name", _protocol_methods())
def test_store_matches_the_protocol_signature(name):
    assert inspect.signature(getattr(Store, name)) == inspect.signature(getattr(DataSource, name))


def test_store_is_a_data_source():
    source: DataSource = Store.load(None, [])
    assert isinstance(source, Store)


def test_importing_the_store_leaves_textual_out():
    src = str(Path(gauntlet.__file__).resolve().parents[1])
    code = "import sys, gauntlet.tui.store; sys.exit('textual' in sys.modules)"
    env = {**os.environ, "PYTHONPATH": src}
    assert subprocess.run([sys.executable, "-c", code], env=env).returncode == 0


def test_store_writes_and_prints_nothing():
    source = Path(store_module.__file__).read_text()
    assert "print(" not in source and "write_text" not in source and '.open("w' not in source


def test_the_real_datasets_load():
    s = Store.load(REPO_DATASETS, [])
    o = s.overview()
    assert o.warnings == ()
    assert o.totals.datasets == SHIPPED_SETS
    assert o.totals.tasks == SHIPPED_TASKS
    assert o.totals.repos == SHIPPED_REPOS
    assert o.totals.leak_check_failures == 0
    assert all(len(s.task(t.instance_id).leakchecks) == len(store_module.LEAK_CHECKS) for t in s.tasks())
    assert {r.id: r.episodes for r in s.runs()} == SHIPPED_EPISODES
    details = {r.id: r.detail for r in s.runs()}
    assert details == {
        "shipped-live-2026-11": "summary",
        "shipped-live-js-2026-11": "summary",
        "shipped-lht-2026-11": "full",
    }
    assert {r.id: r.violations for r in s.runs()}["shipped-lht-2026-11"] == 0
