"""The task record and the patch helpers the harness grader uses.

Before a candidate patch is graded, `strip_test_changes` drops every part of it that touches
tests or test runner config. `extract_patch` reads what an agent changed in its sandbox back
as a git diff.
"""

from __future__ import annotations

import re
import shlex
import time
from pathlib import PurePosixPath

from pydantic import BaseModel, Field

from gauntlet.sandbox import Sandbox

from .repo import Repo2EnvError, is_test_path

# config files that decide what pytest collects. setup.cfg and pyproject.toml matter too, but
# they hold real project settings, so they're left to Cheat Catcher to flag instead.
PYTEST_CONFIG_FILES = {"pytest.ini", ".pytest.ini", "tox.ini"}
_DIFF_HEADER = re.compile(r'^diff --git "?a/(.+?)"? "?b/(.+?)"?$')


class PatchFailed(Repo2EnvError):
    pass


class Task(BaseModel):
    format: str = "gauntlet.task/v1"
    instance_id: str
    repo: str
    image: str
    workdir: str
    base_commit: str
    solution_commit: str
    problem_statement: str
    gold_patch: str
    test_patch: str
    test_files: list[str]
    fail_to_pass: list[str]
    pass_to_pass: list[str]
    created_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------- patch guarding


def split_patch(patch: str) -> list[tuple[list[str], str]]:
    """Split a git-style diff into per-file sections: (paths each one touches, its text).

    Plain diffs without `diff --git` headers come back as one section, which errs on the
    side of dropping too much rather than letting a test edit slip through.
    """
    chunks: list[list[str]] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git ") or not chunks:
            chunks.append([])
        chunks[-1].append(line)

    sections = []
    for lines in chunks:
        paths: set[str] = set()
        m = _DIFF_HEADER.match(lines[0].rstrip("\n"))
        if m:
            paths |= {m.group(1), m.group(2)}
        for ln in lines:
            if ln.startswith("@@") and m:
                break  # a git section's headers are all above its first hunk
            if ln.startswith(("--- ", "+++ ")):
                p = ln[4:].split("\t")[0].strip().strip('"')
                if p != "/dev/null":
                    paths.add(p[2:] if p.startswith(("a/", "b/")) else p)
            elif ln.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                paths.add(ln.split(" ", 2)[2].strip())
        sections.append((sorted(paths), "".join(lines)))
    return sections


# The same idea for JS runners: the files that decide what gets collected and what runs before it.
# package.json is left out for the reason pyproject.toml is. A fix can really need it.
_JS_CONFIG = re.compile(
    r"^(vitest|vite|jest)\.(config|workspace|setup)\.[cm]?[jt]sx?$|^setupTests\.[cm]?[jt]sx?$"
)


def is_js_runner_config(path: str) -> bool:
    """A vitest, vite or jest config or setup file, by name."""
    return bool(_JS_CONFIG.match(PurePosixPath(path).name))


def _grader_owned(path: str, task: Task) -> bool:
    p = PurePosixPath(path)
    if is_test_path(path) or p.name in PYTEST_CONFIG_FILES or path in task.test_files:
        return True
    # node_modules is where the test runner itself lives. The env keeps it outside the repo, but
    # a patch can still write a folder by that name and Node would find it first.
    return "node_modules" in p.parts or bool(_JS_CONFIG.match(p.name))


def strip_test_changes(patch: str, task: Task) -> tuple[str, list[str]]:
    """Drop every part of a patch that touches tests, conftest.py or pytest config.

    Grading should judge the code, not whatever the candidate did to the tests. This is what
    stops a conftest.py hook that rewrites every report to "passed" from scoring a resolve.
    """
    kept, ignored = [], set()
    for paths, text in split_patch(patch):
        owned = [p for p in paths if _grader_owned(p, task)]
        if owned:
            ignored.update(owned)
        else:
            kept.append(text)
    return "".join(kept), sorted(ignored)


# ---------------------------------------------------------------------- agent patches


def extract_patch(sb: Sandbox, task: Task) -> str:
    """Everything the agent changed since `open_task`, as a git diff.

    The diff goes through a file, not stdout. Exec output is capped, and a release-range task's
    patch can run to a few hundred KB (cattrs 26.1.0 -> 26.2.0 is 273 KB), which used to come
    back as an error instead of the agent's work. A fresh mktemp dir means nothing the agent
    left lying around in /tmp can stand in for the file.
    """
    res = sb.exec(
        'd=$(mktemp -d) && git add -A && git diff --cached --binary > "$d/patch" && echo "$d"',
        workdir=task.workdir,
    )
    if not res.ok:
        raise Repo2EnvError(f"couldn't diff: {res.stderr.strip()}")
    where = res.stdout.strip().splitlines()[-1]
    try:
        return sb.read_file(f"{where}/patch").decode("utf-8", errors="surrogateescape")
    finally:
        sb.exec(f"rm -rf {shlex.quote(where)}")
