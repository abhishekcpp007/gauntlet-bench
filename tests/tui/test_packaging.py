import importlib
import inspect
import pkgutil
import re
from pathlib import Path

import gauntlet.tui
import gauntlet.tui.screens

TUI = Path(gauntlet.tui.__file__).parent


def declared_css() -> dict[str, Path]:
    """Every `CSS_PATH` the app and its screens declare, resolved the way Textual does: next to
    the module that defines the class."""
    modules = ["gauntlet.tui.app"] + [
        f"gauntlet.tui.screens.{m.name}" for m in pkgutil.iter_modules(gauntlet.tui.screens.__path__)
    ]
    found: dict[str, Path] = {}
    for name in modules:
        module = importlib.import_module(name)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            paths = cls.__dict__.get("CSS_PATH")
            if cls.__module__ != name or not paths:
                continue
            for path in [paths] if isinstance(paths, str | Path) else paths:
                found[f"{cls.__qualname__}:{path}"] = Path(inspect.getfile(cls)).parent / path
    return found


def test_every_css_path_exists():
    css = declared_css()
    assert len(css) >= len(list(TUI.rglob("*.tcss")))
    missing = [key for key, path in css.items() if not path.is_file()]
    assert not missing


def test_every_tcss_file_is_used():
    used = {path.resolve() for path in declared_css().values()}
    assert {path.resolve() for path in TUI.rglob("*.tcss")} <= used


ROOT = TUI.parents[2]


def test_readme_screenshots_exist_and_show_no_local_paths():
    readme = (ROOT / "README.md").read_text()
    shots = re.findall(r"\]\((docs/tui-[\w-]+\.svg)\)", readme)
    assert len(shots) >= 2
    for shot in shots:
        svg = (ROOT / shot).read_text()
        assert not re.search(r"/Users/|/home/|/private/|/tmp/", svg), shot
