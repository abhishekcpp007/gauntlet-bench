"""What the Workbench checks before it offers to start a job: Docker, free disk and keys.

Only yes or no answers about keys and tokens: their values are never returned, logged or
printed. Every check that touches the OS can be swapped out, so tests never run real Docker.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .jobtypes import Machine
from .workspace import Workspace

DOCKER_TIMEOUT_SECONDS = 5.0
DOCKER_INFO = ("docker", "info", "--format", "{{.ServerVersion}}")
DETAIL_MAX = 200
ANTHROPIC_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
GITHUB_VARS = ("GITHUB_TOKEN", "GH_TOKEN")


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


CommandRunner = Callable[[Sequence[str], float], CommandResult]
DiskFree = Callable[[Path], int]


def run_command(argv: Sequence[str], timeout: float) -> CommandResult:
    """Run `argv` with no shell and no input, and give back its exit code and output."""
    proc = subprocess.run(
        list(argv),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )
    return CommandResult(proc.returncode, proc.stdout, proc.stderr)


def disk_free(path: Path) -> int:
    """Free bytes on the disk that holds `path`, or its nearest folder that exists."""
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def _first_line(text: str) -> str:
    line = next((x.strip() for x in text.splitlines() if x.strip()), "")
    return line[:DETAIL_MAX]


def check_docker(run: CommandRunner = run_command) -> tuple[bool, str]:
    """(running, a plain sentence saying so or saying what went wrong)."""
    try:
        result = run(DOCKER_INFO, DOCKER_TIMEOUT_SECONDS)
    except FileNotFoundError:
        return False, "Docker isn't installed: there's no docker command on this machine."
    except subprocess.TimeoutExpired:
        return False, f"Docker didn't answer within {DOCKER_TIMEOUT_SECONDS:g} seconds."
    except OSError as e:
        return False, f"Couldn't run docker: {e.strerror or e}."
    if result.returncode != 0:
        why = _first_line(result.stderr) or _first_line(result.stdout)
        return False, f"Docker isn't running: {why}" if why else "Docker isn't running."
    version = _first_line(result.stdout)
    return True, f"Docker {version} is running." if version else "Docker is running."


def _is_set(environ: Mapping[str, str], names: Sequence[str]) -> bool:
    return any(environ.get(name) for name in names)


def inspect_machine(
    workspace: Workspace,
    *,
    run: CommandRunner = run_command,
    environ: Mapping[str, str] | None = None,
    free: DiskFree = disk_free,
) -> Machine:
    """Is Docker up, how much disk is free at the workspace, and which keys are set (yes or no)."""
    env = os.environ if environ is None else environ
    running, detail = check_docker(run)
    return Machine(
        docker_running=running,
        docker_detail=detail,
        free_disk_bytes=free(workspace.root),
        anthropic_key_set=_is_set(env, ANTHROPIC_VARS),
        github_token_set=_is_set(env, GITHUB_VARS),
        workspace=str(workspace.root),
    )
