"""Real `gauntlet` processes through `SubprocessJobRunner`: only commands that need no Docker and
no network, on the fixtures in this repo."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from gauntlet.cheatcatcher.cli import EXIT_CODES
from gauntlet.cheatcatcher.rules import RULES
from gauntlet.tui import actions
from gauntlet.tui.jobs import JOB_FILE, SubprocessJobRunner, record_from_json
from gauntlet.tui.jobtypes import FINISHED, JobEvent, JobSpec, Step
from gauntlet.tui.workspace import Workspace

from .fakejobs import fake_machine
from .sample import SAMPLE_RUN

EXAMPLES = Path(__file__).resolve().parents[1] / "cheatcatcher" / "examples"
REAL_TIMEOUT_SECONDS = 60.0
USAGE_ERROR_EXIT = 2


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "work")


@pytest.fixture
def runner(ws):
    made = SubprocessJobRunner(ws, machine=fake_machine)
    yield made
    made.close()


def run(runner: SubprocessJobRunner, spec: JobSpec) -> tuple[list[JobEvent], object]:
    events: list[JobEvent] = []
    done = threading.Event()

    def listen(event: JobEvent) -> None:
        events.append(event)
        if event.kind == "state" and event.record.state in FINISHED:
            done.set()

    runner.subscribe(listen)
    record = runner.submit(spec)
    assert done.wait(REAL_TIMEOUT_SECONDS), f"{spec.title} didn't finish"
    final = runner.job(record.id)
    saved = record_from_json(json.loads((Path(final.log_path).parent / JOB_FILE).read_text()))
    assert saved == final
    return events, final


def lines(events: list[JobEvent]) -> list[str]:
    return [e.text for e in events if e.kind == "line"]


def test_cheatcatcher_rules(runner):
    spec = JobSpec(
        "rules", "List rules", (Step("List the rules", ("cheatcatcher", "rules")),), exclusive=False
    )
    events, final = run(runner, spec)
    assert final.state == "succeeded" and final.exit_code == 0
    printed = lines(events)
    assert [line.split()[0] for line in printed] == list(RULES)
    assert list(runner.log(final.id)) == printed


@pytest.mark.parametrize(
    ("diff", "verdict"),
    [("honest_fix.diff", "clean"), ("conftest_force_pass.diff", "cheating")],
)
def test_scan_a_patch_end_to_end(runner, diff, verdict):
    events, final = run(runner, actions.scan_patch(EXAMPLES / diff))
    assert final.state == "succeeded" and final.exit_code == EXIT_CODES[verdict]
    result = actions.parse_scan("\n".join(runner.log(final.id)))
    assert result.verdict == verdict
    assert all(e.stream == "out" for e in events if e.kind == "line")


def test_a_scan_without_the_ok_codes_fails_on_cheating(runner):
    plain = actions.scan_patch(EXAMPLES / "conftest_force_pass.diff")
    step = plain.steps[0]
    spec = JobSpec(plain.action, plain.title, (Step(step.title, step.argv),), exclusive=False)
    _, final = run(runner, spec)
    assert final.state == "failed" and final.exit_code == EXIT_CODES["cheating"]


def test_report_on_the_sample_run(runner, ws):
    spec = actions.report(ws, SAMPLE_RUN / "results.jsonl", html=True, name="sample")
    events, final = run(runner, spec)
    assert final.state == "succeeded"
    assert any("oracle" in line for line in lines(events))
    page = Path(spec.outputs[0].path)
    assert page.is_file() and page.parent == ws.root / "reports"


def test_a_bad_command_fails_with_its_exit_code(runner):
    spec = JobSpec("bad", "Bad", (Step("Ask for nothing", ("report", "--results")),), exclusive=False)
    events, final = run(runner, spec)
    assert final.state == "failed" and final.exit_code == USAGE_ERROR_EXIT
    assert any(e.stream == "err" and "--results" in e.text for e in events if e.kind == "line")
