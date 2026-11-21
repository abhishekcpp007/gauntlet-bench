"""`FakeJobRunner` behaves like the real runner, so screen tests built on it mean something."""

import pytest

from gauntlet.tui.jobs import RunnerClosed
from gauntlet.tui.jobtypes import JobNotFound, JobRunner, JobSpec, Step

from .fakejobs import INTERRUPTED, NEXT_STEP, FakeJobRunner, fake_machine

FAIL_CODE = 3
CLEAN, SUSPICIOUS, CHEATING = 0, 1, 2


def spec(action="a", *, exclusive=True, steps=2, ok_codes=(0,)):
    return JobSpec(
        action=action,
        title=action,
        steps=tuple(Step(f"Step {n}", ("x",), ok_codes=ok_codes) for n in range(steps)),
        exclusive=exclusive,
    )


def test_it_is_a_job_runner():
    runner: JobRunner = FakeJobRunner()
    assert runner.machine() == fake_machine()


def test_a_scripted_job_moves_one_event_at_a_time():
    runner = FakeJobRunner()
    runner.script("a", ["one", ("two", "err"), NEXT_STEP, "three"])
    heard = []
    runner.subscribe(heard.append)
    record = runner.submit(spec())
    assert runner.job(record.id).state == "queued" and len(heard) == 1
    assert [e.kind for e in runner.step()] == ["state", "step"]
    assert runner.step()[0].text == "one"
    assert runner.step()[0].stream == "err"
    moved = runner.step()[0]
    assert moved.kind == "step" and moved.text == "Step 1" and moved.record.step_index == 1
    runner.run_until_idle()
    assert runner.job(record.id).state == "succeeded"
    assert runner.log(record.id) == ("one", "two", "three")
    assert runner.log(record.id, tail=1) == ("three",)
    assert runner.step() == ()
    assert [e.kind for e in heard] == ["state", "state", "step", "line", "line", "step", "line", "state"]


def test_exit_codes_follow_the_steps_ok_codes():
    runner = FakeJobRunner()
    runner.script("bad", exit_code=FAIL_CODE)
    runner.script("scan", exit_code=CHEATING)
    bad = runner.submit(spec("bad", exclusive=False))
    scan = runner.submit(spec("scan", exclusive=False, ok_codes=(CLEAN, SUSPICIOUS, CHEATING)))
    runner.run_until_idle()
    assert (
        runner.job(bad.id).state == "failed" and f"exited with code {FAIL_CODE}" in runner.job(bad.id).error
    )
    assert runner.job(scan.id).state == "succeeded" and runner.job(scan.id).exit_code == CHEATING


def test_exclusive_jobs_wait_their_turn():
    runner = FakeJobRunner()
    first, second = runner.submit(spec("first")), runner.submit(spec("second"))
    side = runner.submit(spec("side", exclusive=False))
    runner.step()
    runner.step()
    assert runner.job(first.id).state == "running" and runner.job(side.id).state == "running"
    assert runner.job(second.id).state == "queued"
    runner.run_until_idle()
    assert all(runner.job(r.id).state == "succeeded" for r in (first, second, side))
    assert runner.job(first.id).finished_at < runner.job(second.id).started_at


def test_cancel_and_close():
    runner = FakeJobRunner()
    queued, running = runner.submit(spec("q")), runner.submit(spec("r", exclusive=False))
    runner.start(running.id)
    runner.cancel(queued.id)
    runner.cancel(running.id)
    assert runner.job(queued.id).state == runner.job(running.id).state == "cancelled"
    assert runner.cancel_requests == [queued.id, running.id]
    left = runner.submit(spec("left"))
    runner.close()
    assert runner.closed and runner.job(left.id).state == "cancelled"
    with pytest.raises(RunnerClosed):
        runner.submit(spec())
    with pytest.raises(JobNotFound):
        runner.job("nope")


def test_by_hand_and_seeded_history():
    runner = FakeJobRunner(machine=fake_machine(docker_running=False))
    assert not runner.machine().docker_running
    past = runner.seed(spec("old"), state="failed", error=INTERRUPTED, lines=["was here"])
    job = runner.submit(spec("new"))
    runner.start(job.id)
    runner.emit(job.id, "hello")
    runner.next_step(job.id)
    runner.finish(job.id, exit_code=FAIL_CODE, error="broke")
    assert runner.job(job.id).error == "broke" and runner.job(job.id).step_index == 1
    assert [r.id for r in runner.jobs()] == [job.id, past.id]
    assert runner.log(past.id) == ("was here",) and runner.job(past.id).error == INTERRUPTED
    assert runner.submitted == [spec("new")]


def test_a_listener_that_raises_is_recorded_and_the_rest_still_hear():
    runner = FakeJobRunner()

    def bad(event):
        raise RuntimeError("boom")

    heard = []
    runner.subscribe(bad)
    unsubscribe = runner.subscribe(heard.append)
    runner.submit(spec())
    unsubscribe()
    runner.run_until_idle()
    assert len(heard) == 1 and runner.listener_errors


def test_log_lines_keep_each_lines_stream():
    runner = FakeJobRunner()
    runner.script("scan_patch", ["clean", ("warned", "err")])
    record = runner.submit(JobSpec(action="scan_patch", title="Scan", steps=(Step("Scan", ("rules",)),)))
    runner.run_until_idle()
    assert [(line.text, line.stream) for line in runner.log_lines(record.id)] == [
        ("clean", "out"),
        ("warned", "err"),
    ]
    assert [line.text for line in runner.log_lines(record.id, tail=1)] == ["warned"]
    seeded = runner.seed(record.spec, lines=["a", ("b", "err")])
    assert [line.stream for line in runner.log_lines(seeded.id)] == ["out", "err"]
