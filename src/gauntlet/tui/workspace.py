"""The Workbench's workspace: the one folder every job writes into.

    <root>/tasks/<name>/    a task set: prs.jsonl, tasks.jsonl, rejected.jsonl
    <root>/runs/<name>/     a normal run folder: results.jsonl, trajectories/, rl/
    <root>/reports/         HTML reports
    <root>/jobs/<id>/       a job's record (job.json) and its full log (log.txt)

Jobs never write outside it, and it can't live inside a `datasets` folder, so the shipped task
sets stay untouched. Folders are made when they're first asked for. Plain Python, no Textual.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

TASKS_DIR = "tasks"
RUNS_DIR = "runs"
REPORTS_DIR = "reports"
JOBS_DIR = "jobs"
DATASETS_DIR = "datasets"
DEFAULT_WORKSPACE = "gauntlet-work"

STAMP_FORMAT = "%Y%m%d-%H%M%S"
SLUG_MAX = 40
DEFAULT_SLUG = "work"
FIRST_COUNTER = 2
NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")

Kind = Literal["tasks", "runs", "reports"]
Clock = Callable[[], datetime]


class WorkspaceError(ValueError):
    """A workspace path or name that can't be used, with a message that says why."""


def slugify(text: str) -> str:
    """Lower case letters, digits and single dashes, at most `SLUG_MAX` long."""
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:SLUG_MAX].rstrip("-") or DEFAULT_SLUG


def check_name(name: str) -> str:
    """A folder name for a task set or run: letters, digits, `_`, `.` and `-`, not starting with
    a dot or a dash. Returns it unchanged, or raises `WorkspaceError`."""
    if not NAME_PATTERN.fullmatch(name):
        raise WorkspaceError(
            f"{name!r} can't be a folder name. Use letters, digits, '_', '.' and '-', and start "
            "with a letter or a digit"
        )
    return name


class Workspace:
    """The folder every Workbench job writes into. See the module docstring for its layout.

    `root` is resolved, symlinks and all, so every check below compares real paths. `clock`
    gives the time used in new names, and tests pass a fixed one.
    """

    def __init__(self, root: Path | str, *, clock: Clock = datetime.now) -> None:
        resolved = Path(root).expanduser().resolve()
        if DATASETS_DIR in resolved.parts:
            raise WorkspaceError(
                f"The workspace {resolved} is inside a {DATASETS_DIR!r} folder. Pick a folder outside it, "
                "so jobs never write next to the shipped task sets"
            )
        if resolved.exists() and not resolved.is_dir():
            raise WorkspaceError(f"The workspace {resolved} is a file, not a folder")
        self._root = resolved
        self._clock = clock
        self._handed_out: set[tuple[Kind, str]] = set()

    @property
    def root(self) -> Path:
        return self._root

    def _folder(self, *parts: str) -> Path:
        path = self.inside(self._root.joinpath(*parts))
        path.mkdir(parents=True, exist_ok=True)
        return path

    def tasks_dir(self, name: str) -> Path:
        """`tasks/<name>/`, made if it's missing."""
        return self._folder(TASKS_DIR, check_name(name))

    def run_dir(self, name: str) -> Path:
        """`runs/<name>/`, made if it's missing."""
        return self._folder(RUNS_DIR, check_name(name))

    def reports_dir(self) -> Path:
        """`reports/`, made if it's missing."""
        return self._folder(REPORTS_DIR)

    def job_dir(self, job_id: str) -> Path:
        """`jobs/<id>/`, made if it's missing."""
        return self._folder(JOBS_DIR, check_name(job_id))

    def jobs_root(self) -> Path:
        """`jobs/`, made if it's missing."""
        return self._folder(JOBS_DIR)

    def path_for(self, kind: Kind, name: str) -> Path:
        """Where `name` of this kind lives, without making anything."""
        return self.inside(self._root / kind / check_name(name))

    def new_name(self, kind: Kind, label: str) -> str:
        """A fresh name like `pallets-click-20261122-143005`: readable, and sorted by time.

        A counter (`-2`, `-3`) is added while a folder or a file of that name exists, or this
        workspace already gave the name out. Nothing is made on disk.
        """
        base = f"{slugify(label)}-{self._clock().strftime(STAMP_FORMAT)}"
        name, counter = base, FIRST_COUNTER
        while (kind, name) in self._handed_out or self._taken(kind, name):
            name = f"{base}-{counter}"
            counter += 1
        self._handed_out.add((kind, name))
        return name

    def _taken(self, kind: Kind, name: str) -> bool:
        folder = self._root / kind
        return folder.is_dir() and any(p.name == name or p.stem == name for p in folder.iterdir())

    def task_sets(self) -> tuple[Path, ...]:
        """Every folder under `tasks/`, by name. A set still being made is listed too."""
        return self._listing(TASKS_DIR)

    def runs(self) -> tuple[Path, ...]:
        """Every folder under `runs/`, by name. A run still going is listed too."""
        return self._listing(RUNS_DIR)

    def _listing(self, kind: str) -> tuple[Path, ...]:
        folder = self._root / kind
        if not folder.is_dir():
            return ()
        return tuple(sorted((p for p in folder.iterdir() if p.is_dir()), key=lambda p: p.name))

    def contains(self, path: Path | str) -> bool:
        """True when `path`, with every symlink followed, is the root or inside it."""
        return Path(path).expanduser().resolve().is_relative_to(self._root)

    def inside(self, path: Path | str) -> Path:
        """`path` resolved, or `WorkspaceError` when it lands outside the workspace."""
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_relative_to(self._root):
            raise WorkspaceError(f"{path} is outside the workspace {self._root}")
        return resolved
