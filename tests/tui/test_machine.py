import errno
import subprocess

import pytest

from gauntlet.tui import machine as machine_module
from gauntlet.tui.machine import (
    DOCKER_INFO,
    DOCKER_TIMEOUT_SECONDS,
    CommandResult,
    check_docker,
    disk_free,
    inspect_machine,
)
from gauntlet.tui.workspace import Workspace

FREE = 12_345_678
FAKE_SECRET = "sk-fake-test-value-not-a-key"


def answer(code: int, out: str = "", err: str = ""):
    calls = []

    def run(argv, timeout):
        calls.append((tuple(argv), timeout))
        return CommandResult(code, out, err)

    run.calls = calls
    return run


def raising(error: Exception):
    def run(argv, timeout):
        raise error

    return run


def test_docker_running_names_its_version():
    run = answer(0, "28.1.1\n")
    assert check_docker(run) == (True, "Docker 28.1.1 is running.")
    assert run.calls == [(DOCKER_INFO, DOCKER_TIMEOUT_SECONDS)]


@pytest.mark.parametrize(
    ("run", "words"),
    [
        (
            answer(1, err="\nCannot connect to the Docker daemon at unix:///var/run/docker.sock\n"),
            "Cannot connect",
        ),
        (answer(1), "isn't running."),
        (raising(FileNotFoundError("docker")), "isn't installed"),
        (raising(subprocess.TimeoutExpired("docker", DOCKER_TIMEOUT_SECONDS)), "didn't answer"),
        (raising(PermissionError(errno.EACCES, "Permission denied")), "Permission denied"),
    ],
)
def test_docker_problems_are_said_plainly(run, words):
    running, detail = check_docker(run)
    assert not running and words in detail


def test_machine_reports_keys_as_yes_or_no_only(tmp_path):
    ws = Workspace(tmp_path / "w")
    env = {"ANTHROPIC_AUTH_TOKEN": FAKE_SECRET, "GH_TOKEN": FAKE_SECRET}
    m = inspect_machine(ws, run=answer(0, "1"), environ=env, free=lambda _: FREE)
    assert m.docker_running and m.anthropic_key_set and m.github_token_set
    assert m.free_disk_bytes == FREE and m.workspace == str(ws.root)
    assert FAKE_SECRET not in repr(m)
    none = inspect_machine(ws, run=answer(1), environ={"ANTHROPIC_API_KEY": ""}, free=lambda _: FREE)
    assert not (none.docker_running or none.anthropic_key_set or none.github_token_set)


def test_machine_reads_the_real_environment_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", FAKE_SECRET)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    m = inspect_machine(Workspace(tmp_path), run=answer(0), free=lambda _: FREE)
    assert m.anthropic_key_set and not m.github_token_set


def test_disk_free_walks_up_to_a_folder_that_exists(tmp_path):
    assert disk_free(tmp_path / "not" / "yet") == disk_free(tmp_path) > 0


def test_the_default_runner_uses_no_shell(monkeypatch):
    seen = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs, argv=argv)
        return subprocess.CompletedProcess(argv, 0, "v\n", "")

    monkeypatch.setattr(machine_module.subprocess, "run", fake_run)
    result = machine_module.run_command(DOCKER_INFO, DOCKER_TIMEOUT_SECONDS)
    assert result == CommandResult(0, "v\n", "")
    assert seen["argv"] == list(DOCKER_INFO) and "shell" not in seen
    assert seen["timeout"] == DOCKER_TIMEOUT_SECONDS
