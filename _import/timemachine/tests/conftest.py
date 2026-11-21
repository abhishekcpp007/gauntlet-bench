import docker
import pytest
from gauntlet_sandbox import Trajectory, TrajectoryHeader

IMAGE = "python:3.12-slim"


def _docker_ok() -> bool:
    try:
        docker.from_env().ping()
        return True
    except Exception:
        return False


DOCKER_OK = _docker_ok()


def pytest_collection_modifyitems(config, items):
    if DOCKER_OK:
        return
    skip = pytest.mark.skip(reason="Docker daemon not reachable")
    for item in items:
        if "docker" in item.keywords:
            item.add_marker(skip)


def exec_step(command: str, stdout: str = "", exit_code: int = 0, **extra) -> tuple[dict, dict]:
    action = {"type": "exec", "command": command, "timeout": 30, "workdir": None, "env": None}
    obs = {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": "",
        "duration": 0.05,
        "timed_out": False,
        "truncated": False,
    }
    obs.update(extra)
    return action, obs


def make_traj(*steps: tuple[dict, dict], sandbox_id: str = "abc123") -> Trajectory:
    traj = Trajectory(TrajectoryHeader(sandbox_id=sandbox_id, image=IMAGE, created_at=1_700_000_000.0))
    for action, obs in steps:
        traj.record(action, obs)
    return traj
