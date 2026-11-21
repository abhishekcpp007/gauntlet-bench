"""`SubprocessJobRunner` with fake processes: no real child, no Docker."""

from __future__ import annotations

import errno
import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from gauntlet.tui import jobs as jobs_module
from gauntlet.tui.jobs import (
    HARNESS_MODULE,
    INTERRUPTED,
    JOB_FILE,
    LOG_FILE,
    RunnerClosed,
    SubprocessJobRunner,
    child_environment,
    format_job_id,
    record_from_json,
    record_to_json,
    source_root,
    tail_lines,
)
from gauntlet.tui.jobtypes import FINISHED, JobEvent, JobNotFound, JobSpec, Output, Step

from .fakejobs import fake_machine

WAIT_SECONDS = 5.0
POLL_SECONDS = 0.005
GRACE = 0.02
LONG_GRACE = 60.0
NOW = 1_795_000_000.0
FAIL_CODE = 3
SUSPICIOUS = 1
BIG_LOG_LINES = 200_000
TAIL = 5
SIGINT_CODE = -signal.SIGINT
SIGTERM_CODE = -signal.SIGTERM
SIGKILL_CODE = -signal.SIGKILL


class FakeProcess:
    """Prints its output at once. A `blocking` one runs until a signal it `obeys`, or `release()`."""

    def __init__(
        self,
        out: str | bytes = "",
        err: str | bytes = "",
        code: int = 0,
        *,
        blocking: bool = False,
        obeys: tuple[str, ...] = ("interrupt", "terminate"),
    ) -> None:
        self.stdout = io.BytesIO(out if isinstance(out, bytes) else out.encode())
        self.stderr = io.BytesIO(err if isinstance(err, bytes) else err.encode())
        self.signals: list[str] = []
        self.obeys = obeys
        self._code = code
        self._exited = threading.Event()
        if not blocking:
            self._exited.set()

    def wait(self, timeout: float | None = None) -> int:
        if not self._exited.wait(timeout):
            raise subprocess.TimeoutExpired("fake", timeout or 0)
        return self._code

    def release(self, code: int = 0) -> None:
        self._code = code
        self._exited.set()

    def _signal(self, name: str, code: int) -> None:
        self.signals.append(name)
        if name in self.obeys or name == "kill":
            self.release(code)

    def interrupt(self) -> None:
        self._signal("interrupt", SIGINT_CODE)

    def terminate(self) -> None:
        self._signal("terminate", SIGTERM_CODE)

    def kill(self) -> None:
        self._signal("kill", SIGKILL_CODE)


class Factory:
    def __init__(self, *processes: FakeProcess) -> None:
        self.processes = list(processes)
        self.calls: list[tuple[list[str], dict[str, str], Path]] = []
        self.started = threading.Semaphore(0)

    def __call__(self, argv, env, cwd):
        self.calls.append((list(argv), dict(env), cwd))
        self.started.release()
        return self.processes.pop(0)


def spec(action: str = "a", *steps: Step, exclusive: bool = True) -> JobSpec:
    return JobSpec(
        action=action,
        title=f"Job {action}",
        steps=steps or (Step("First", ("cheatcatcher", "rules")),),
        outputs=(Output("run", "/x", "Run", episode_id="e"),),
        exclusive=exclusive,
    )


def wait_until(check, what: str = "the condition") -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(POLL_SECONDS)


def finished(runner, job_id):
    wait_until(lambda: runner.job(job_id).state in FINISHED, f"job {job_id} to finish")
    return runner.job(job_id)


@pytest.fixture
def make(tmp_path):
    from gauntlet.tui.workspace import Workspace

    made = []

    def build(factory, **kwargs):
        kwargs.setdefault("interrupt_grace", GRACE)
        kwargs.setdefault("terminate_grace", GRACE)
        kwargs.setdefault("machine", fake_machine)
        kwargs.setdefault("environ", {"HOME": "/home/x"})
        runner = SubprocessJobRunner(Workspace(tmp_path / "ws"), start=factory, **kwargs)
        made.append(runner)
        return runner

    yield build
    for runner in made:
        runner.close()


def test_a_step_runs_the_harness_and_logs_both_streams(make, tmp_path):
    factory = Factory(FakeProcess("one\ntwo\n", b"warn \xff\r\n"))
    runner = make(factory, python="/py")
    events: list[JobEvent] = []
    runner.subscribe(events.append)
    record = runner.submit(spec())
    done = finished(runner, record.id)
    assert done.state == "succeeded" and done.exit_code == 0 and done.started_at and done.finished_at
    argv, env, cwd = factory.calls[0]
    assert argv == ["/py", "-m", HARNESS_MODULE, "cheatcatcher", "rules"]
    assert env["PYTHONUNBUFFERED"] == "1" and env["HOME"] == "/home/x"
    assert cwd == tmp_path / "ws"
    lines = [(e.text, e.stream) for e in events if e.kind == "line"]
    assert sorted(lines) == sorted([("one", "out"), ("two", "out"), ("warn �", "err")])
    assert sorted(runner.log(record.id)) == ["one", "two", "warn �"]
    kinds = [(e.kind, e.record.state) for e in events if e.kind != "line"]
    assert kinds == [("state", "queued"), ("state", "running"), ("step", "running"), ("state", "succeeded")]
    saved = json.loads((Path(done.log_path).parent / JOB_FILE).read_text())
    assert record_from_json(saved) == done


def test_steps_run_in_order_and_a_failing_step_stops_the_job(make):
    factory = Factory(FakeProcess("a\n"), FakeProcess(code=FAIL_CODE), FakeProcess())
    runner = make(factory)
    steps = (Step("One", ("x",)), Step("Two", ("y",)), Step("Three", ("z",)))
    done = finished(runner, runner.submit(spec("a", *steps)).id)
    assert done.state == "failed" and done.exit_code == FAIL_CODE and done.step_index == 1
    assert done.error == f"Two exited with code {FAIL_CODE}"
    assert [c[0][-1] for c in factory.calls] == ["x", "y"]


def test_ok_codes_make_a_non_zero_exit_a_success(make):
    runner = make(Factory(FakeProcess(code=SUSPICIOUS)))
    done = finished(runner, runner.submit(spec("scan", Step("Scan", ("s",), ok_codes=(0, SUSPICIOUS)))).id)
    assert done.state == "succeeded" and done.exit_code == SUSPICIOUS


def test_exclusive_jobs_queue_and_others_start_at_once(make):
    first, second, side = FakeProcess(blocking=True), FakeProcess(), FakeProcess(blocking=True)
    factory = Factory(first, side, second)
    runner = make(factory)
    a = runner.submit(spec("a"))
    assert factory.started.acquire(timeout=WAIT_SECONDS)
    b = runner.submit(spec("b"))
    c = runner.submit(spec("c", exclusive=False))
    assert factory.started.acquire(timeout=WAIT_SECONDS)
    assert runner.job(b.id).state == "queued" and runner.job(c.id).state == "running"
    first.release()
    assert finished(runner, b.id).state == "succeeded"
    assert finished(runner, a.id).state == "succeeded"
    side.release()
    assert finished(runner, c.id).state == "succeeded"
    assert len(factory.calls) == len((a, b, c))


def test_cancel_a_queued_job_at_once(make):
    first = FakeProcess(blocking=True)
    factory = Factory(first)
    runner = make(factory)
    a = runner.submit(spec("a"))
    b = runner.submit(spec("b"))
    runner.cancel(b.id)
    assert runner.job(b.id).state == "cancelled" and runner.job(b.id).started_at is None
    first.release()
    assert finished(runner, a.id).state == "succeeded"
    assert len(factory.calls) == 1
    runner.cancel(b.id)
    with pytest.raises(JobNotFound):
        runner.cancel("nope")


@pytest.mark.parametrize(
    ("obeys", "sent", "code"),
    [
        (("interrupt", "terminate"), ["interrupt"], SIGINT_CODE),
        (("terminate",), ["interrupt", "terminate"], SIGTERM_CODE),
        ((), ["interrupt", "terminate", "kill"], SIGKILL_CODE),
    ],
    ids=("interrupt", "terminate", "kill"),
)
def test_cancel_a_running_job_escalates(make, obeys, sent, code):
    proc = FakeProcess(blocking=True, obeys=obeys)
    factory = Factory(proc)
    runner = make(factory)
    record = runner.submit(spec())
    assert factory.started.acquire(timeout=WAIT_SECONDS)
    runner.cancel(record.id)
    done = finished(runner, record.id)
    assert done.state == "cancelled" and done.exit_code == code
    assert proc.signals == sent
    assert any("interrupt" in line for line in runner.log(record.id))


def test_cancel_between_steps_stops_before_the_next(make):
    first = FakeProcess(blocking=True, obeys=())
    factory = Factory(first, FakeProcess())
    runner = make(factory, interrupt_grace=LONG_GRACE)
    record = runner.submit(spec("a", Step("One", ("x",)), Step("Two", ("y",))))
    assert factory.started.acquire(timeout=WAIT_SECONDS)
    runner.cancel(record.id)
    wait_until(lambda: first.signals == ["interrupt"], "the interrupt")
    first.release()
    assert finished(runner, record.id).state == "cancelled"
    assert len(factory.calls) == 1


def test_a_process_that_cant_start_fails_the_job(make):
    def broken(argv, env, cwd):
        raise FileNotFoundError(errno.ENOENT, "No such file", argv[0])

    runner = make(broken)
    done = finished(runner, runner.submit(spec()).id)
    assert done.state == "failed" and "couldn't start first" in done.error and done.exit_code is None


def test_a_listener_that_raises_breaks_nothing(make):
    runner = make(Factory(FakeProcess("hi\n")))
    heard: list[str] = []

    def bad(event):
        raise RuntimeError("boom")

    runner.subscribe(bad)
    runner.subscribe(lambda e: heard.append(e.kind))
    gone: list[str] = []
    unsubscribe = runner.subscribe(lambda e: gone.append(e.kind))
    unsubscribe()
    unsubscribe()
    done = finished(runner, runner.submit(spec()).id)
    assert done.state == "succeeded"
    wait_until(lambda: heard[-1] == "state" and "line" in heard, "the events")
    assert gone == []


def test_history_survives_a_restart_and_interrupted_jobs_fail(make, tmp_path):
    hung = FakeProcess(blocking=True, obeys=())
    factory = Factory(FakeProcess("kept\n"), hung, FakeProcess())
    first = make(factory, clock=lambda: NOW)
    done = finished(first, first.submit(spec("done")).id)
    stuck = first.submit(spec("stuck"))
    waiting = first.submit(spec("waiting"))
    wait_until(lambda: first.job(stuck.id).state == "running", "the job to start")
    second = make(Factory(), clock=lambda: NOW)
    ids = [r.id for r in second.jobs()]
    assert ids == sorted(ids, reverse=True) == [waiting.id, stuck.id, done.id]
    assert second.job(done.id) == first.job(done.id)
    assert second.log(done.id) == ("kept",)
    for job_id in (stuck.id, waiting.id):
        again = second.job(job_id)
        assert again.state == "failed" and again.error == INTERRUPTED and again.finished_at
        on_disk = record_from_json(json.loads((Path(again.log_path).parent / JOB_FILE).read_text()))
        assert on_disk.state == "failed"
    hung.release()


def test_a_broken_record_is_skipped_with_a_warning(make, tmp_path):
    folder = tmp_path / "ws" / "jobs" / "20261122-000000-001"
    folder.mkdir(parents=True)
    (folder / JOB_FILE).write_text("{not json")
    (tmp_path / "ws" / "jobs" / "empty").mkdir()
    runner = make(Factory())
    assert runner.jobs() == () and "isn't a job record" in runner.load_warnings[0]


def test_ids_are_unique_and_sort_by_time(make):
    factory = Factory(FakeProcess(), FakeProcess(), FakeProcess())
    runner = make(factory, clock=lambda: NOW)
    ids = [runner.submit(spec(exclusive=False)).id for _ in range(len(factory.processes))]
    assert ids == [format_job_id(NOW, n) for n in (1, 2, 3)]
    assert format_job_id(NOW, 1) < format_job_id(NOW + 1, 1)


def test_log_tail_reads_only_the_end_of_a_big_file(make, monkeypatch):
    runner = make(Factory(FakeProcess()))
    record = finished(runner, runner.submit(spec()).id)
    path = Path(record.log_path)
    path.write_text("".join(f"line {i}\n" for i in range(BIG_LOG_LINES)))

    def no_whole_reads(*_, **__):
        raise AssertionError("read the whole log")

    monkeypatch.setattr(Path, "read_text", no_whole_reads)
    monkeypatch.setattr(Path, "read_bytes", no_whole_reads)
    expected = tuple(f"line {i}" for i in range(BIG_LOG_LINES - TAIL, BIG_LOG_LINES))
    assert runner.log(record.id, tail=TAIL) == expected
    assert runner.log(record.id, tail=0) == ()


def test_tail_lines_edges(tmp_path):
    path = tmp_path / LOG_FILE
    assert tail_lines(path, TAIL) == ()
    path.write_text("a\nb")
    assert tail_lines(path, TAIL) == ("a", "b")
    path.write_text("x" * (jobs_module.TAIL_BLOCK_BYTES * 2) + "\nlast\n")
    assert tail_lines(path, 1) == ("last",)


def test_close_cancels_everything_and_refuses_more(make):
    hung, waiting = FakeProcess(blocking=True, obeys=()), FakeProcess()
    factory = Factory(hung, waiting)
    runner = make(factory, interrupt_grace=LONG_GRACE, terminate_grace=LONG_GRACE, close_timeout=GRACE)
    a = runner.submit(spec("a"))
    b = runner.submit(spec("b"))
    assert factory.started.acquire(timeout=WAIT_SECONDS)
    started = time.monotonic()
    runner.close()
    assert time.monotonic() - started < WAIT_SECONDS
    assert runner.job(b.id).state == "cancelled"
    assert finished(runner, a.id).state == "cancelled" and "kill" in hung.signals
    with pytest.raises(RunnerClosed):
        runner.submit(spec())
    runner.close()


def test_machine_comes_from_the_injected_check(make):
    assert make(Factory()).machine() == fake_machine()


def test_records_round_trip_through_json():
    from gauntlet.tui.jobtypes import JobRecord

    record = JobRecord(
        id="20261122-000000-001",
        spec=spec("scan", Step("Scan", ("s",), ok_codes=(0, SUSPICIOUS))),
        state="failed",
        created_at=NOW,
        log_path="/x/log.txt",
        exit_code=FAIL_CODE,
        error="e",
    )
    raw = json.loads(json.dumps(record_to_json(record)))
    assert record_from_json({**raw, "added_later": 1}) == record


def test_child_environment_makes_the_checkout_importable(tmp_path):
    env = child_environment(
        {"PYTHONPATH": os.pathsep.join(["src", "", "/abs"]), "K": "v"}, tmp_path / "root", tmp_path
    )
    assert env["PYTHONPATH"].split(os.pathsep) == [str(tmp_path / "root"), str(tmp_path / "src"), "/abs"]
    assert env["K"] == "v" and env["PYTHONUNBUFFERED"] == "1"
    again = child_environment({"PYTHONPATH": str(tmp_path / "root")}, tmp_path / "root", tmp_path)
    assert again["PYTHONPATH"] == str(tmp_path / "root")
    assert "PYTHONPATH" not in child_environment({}, None)


def test_source_root_is_the_src_folder_here_and_none_when_installed(monkeypatch):
    import gauntlet

    root = Path(gauntlet.__file__).resolve().parent.parent
    assert source_root() == root
    monkeypatch.setattr(jobs_module.site, "getsitepackages", lambda: [str(root)])
    assert source_root() is None


@pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX")
def test_the_real_process_starts_its_own_group(tmp_path):
    proc = jobs_module.PopenProcess(
        [sys.executable, "-c", "import os; print(os.getpgid(0) == os.getpid())"], {}, tmp_path
    )
    assert proc.stdout.read().strip() == b"True"
    assert proc.wait(WAIT_SECONDS) == 0


def test_log_lines_say_which_stream_each_line_came_from(make, tmp_path):
    factory = Factory(FakeProcess("one\ntwo\n", "warn\n"))
    runner = make(factory, clock=lambda: NOW)
    record = runner.submit(spec())
    finished(runner, record.id)
    lines = runner.log_lines(record.id)
    assert sorted((line.text, line.stream) for line in lines) == [
        ("one", "out"),
        ("two", "out"),
        ("warn", "err"),
    ]
    assert [line.text for line in lines] == list(runner.log(record.id))
    assert runner.log_lines(record.id, tail=1) == lines[-1:]
    again = make(Factory(), clock=lambda: NOW)
    assert again.log_lines(record.id) == lines


def test_a_log_from_before_streams_were_recorded_has_no_stream(make):
    runner = make(Factory(FakeProcess("old\n")), clock=lambda: NOW)
    record = runner.submit(spec())
    done = finished(runner, record.id)
    (Path(done.log_path).parent / jobs_module.STREAMS_FILE).unlink()
    assert [(line.text, line.stream) for line in runner.log_lines(record.id)] == [("old", None)]


def test_tail_streams_pads_missing_letters(tmp_path):
    path = tmp_path / jobs_module.STREAMS_FILE
    assert jobs_module.tail_streams(path, TAIL) == "-" * TAIL
    path.write_text("oe")
    assert jobs_module.tail_streams(path, TAIL) == "---oe"
    assert jobs_module.tail_streams(path, 1) == "e"
    assert jobs_module.tail_streams(path, 0) == ""
