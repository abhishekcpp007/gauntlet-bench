"""Record real runs in Docker, then replay and branch them."""

import shutil

import pytest
from gauntlet_sandbox import Sandbox, SandboxConfig, Trajectory

from gauntlet_timemachine import ReplayError, branch, replay
from gauntlet_timemachine.cli import main

from .conftest import IMAGE

pytestmark = pytest.mark.docker


def _record(path, actions):
    with Sandbox(SandboxConfig(image=IMAGE), trajectory_path=path) as sb:
        actions(sb)
    return Trajectory.load(path)


def _steady_run(sb):
    sb.write_file("app.py", "import sys\nprint('sum', sum(range(10)))\nsys.exit(3)\n")
    sb.exec("python app.py")
    sb.exec("echo oops >&2; ls")
    sb.read_file("app.py")
    sb.client.images.remove(sb.snapshot(label="checkpoint"))
    sb.exec("mkdir -p out && echo done > out/flag && cat out/flag")


def test_replay_is_deterministic(tmp_path):
    traj = _record(tmp_path / "run.jsonl", _steady_run)
    assert len(traj) == 6
    report = replay(traj)
    assert report.steps_replayed == 6
    assert report.deterministic, report.divergences


def test_replay_upto(tmp_path):
    traj = _record(tmp_path / "run.jsonl", _steady_run)
    assert replay(traj, upto=2).steps_replayed == 2
    with pytest.raises(ValueError):
        replay(traj, upto=99)


def test_divergence_is_caught(tmp_path):
    def run(sb):
        sb.exec("echo stable")
        sb.exec("date +%s%N")

    traj = _record(tmp_path / "run.jsonl", run)
    report = replay(traj, trajectory_path=tmp_path / "replay.jsonl")
    assert not report.deterministic
    assert [(d.step, d.field) for d in report.divergences] == [(1, "stdout")]
    # the replay keeps its own record
    assert Trajectory.load(tmp_path / "replay.jsonl").header.metadata["replay_of"] == traj.header.sandbox_id


def test_branch_restores_state(tmp_path):
    def run(sb):
        sb.write_file("notes.txt", "v1\n")
        sb.exec("echo appended >> notes.txt")
        sb.write_file("notes.txt", "v2\n")
        sb.exec("rm notes.txt")

    traj = _record(tmp_path / "run.jsonl", run)
    sb = branch(traj, 2, trajectory_path=tmp_path / "branch.jsonl")
    try:
        assert sb.running
        assert sb.read_text("notes.txt") == "v1\nappended\n"
        sb.exec("echo different path >> notes.txt")
    finally:
        sb.close()

    new = Trajectory.load(tmp_path / "branch.jsonl")
    assert new.header.metadata["branched_from"] == traj.header.sandbox_id
    assert new.header.metadata["branched_at"] == 2
    # 2 replayed steps, then the read and the new command
    assert [s.action["type"] for s in new] == ["write_file", "exec", "read_file", "exec"]


def test_put_archive_replays_from_blob(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "main.py").write_text("print('from the archive')\n")

    def run(sb):
        sb.copy_in(proj, "proj")
        sb.exec("python proj/main.py")

    path = tmp_path / "run.jsonl"
    traj = _record(path, run)
    assert replay(traj).deterministic

    shutil.rmtree(tmp_path / "run.blobs")
    with pytest.raises(ReplayError, match="blobs"):
        replay(Trajectory.load(path))


def test_cli_replay_exit_codes(tmp_path):
    steady = tmp_path / "steady.jsonl"
    _record(steady, lambda sb: sb.exec("echo same"))
    assert main(["replay", str(steady)]) == 0

    noisy = tmp_path / "noisy.jsonl"
    _record(noisy, lambda sb: sb.exec("cat /proc/sys/kernel/random/uuid"))
    assert main(["replay", str(noisy)]) == 1
