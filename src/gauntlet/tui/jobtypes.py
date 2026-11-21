"""What the Workbench runs: jobs made of `gauntlet` commands, and the runner that owns them.

A job is one or more harness commands run in order, exactly as a person would type them. The
Workbench never grades anything itself. It builds the command lines, the runner starts them as
separate processes, and screens watch their output. Screens depend on `JobRunner` only, so tests
can hand them a fake.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

JobState = Literal["queued", "running", "succeeded", "failed", "cancelled"]
Need = Literal["docker", "network", "api_key"]
OutputKind = Literal["prs", "tasks", "rejected", "run", "report", "scan", "text"]
EventKind = Literal["state", "step", "line"]
Stream = Literal["out", "err"]
ActionGroup = Literal["make", "check", "score"]

FINISHED: frozenset[JobState] = frozenset({"succeeded", "failed", "cancelled"})
SUCCESS = 0


class JobNotFound(LookupError):
    """No job with that id."""


@dataclass(frozen=True, slots=True)
class Step:
    """One command of a job: `gauntlet <argv...>`.

    `ok_codes` are the exit codes that mean the step worked. Most commands only have 0, but
    `cheatcatcher scan` exits 1 for suspicious and 2 for cheating, and that's a finished scan.
    """

    title: str
    argv: tuple[str, ...]
    ok_codes: tuple[int, ...] = (SUCCESS,)


@dataclass(frozen=True, slots=True)
class Output:
    """A file or folder a job writes, so the Workbench can open the result afterwards.

    `episode_id` is set when the output is one known episode in a run folder: "Try a patch"
    names the episode it'll make, so the Workbench can open it straight after.
    """

    kind: OutputKind
    path: str
    label: str
    episode_id: str | None = None


@dataclass(frozen=True, slots=True)
class JobSpec:
    """Everything needed to run a job, and to tell the user what it'll do before it starts."""

    action: str
    title: str
    steps: tuple[Step, ...]
    needs: tuple[Need, ...] = ()
    outputs: tuple[Output, ...] = ()
    exclusive: bool = True


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    spec: JobSpec
    state: JobState
    created_at: float
    log_path: str
    step_index: int = 0
    started_at: float | None = None
    finished_at: float | None = None
    exit_code: int | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class JobEvent:
    """Something that happened to a job. `text` is a log line for `line`, a step title for `step`."""

    kind: EventKind
    record: JobRecord
    text: str = ""
    stream: Stream | None = None


@dataclass(frozen=True, slots=True)
class ActionInfo:
    """One action the Workbench offers, for its list. `needs` is what it always needs; a job
    can need more (a `claude:` policy adds `api_key`)."""

    id: str
    title: str
    group: ActionGroup
    description: str
    needs: tuple[Need, ...] = ()


@dataclass(frozen=True, slots=True)
class Machine:
    """What the Workbench checks before it offers to start a job."""

    docker_running: bool
    docker_detail: str
    free_disk_bytes: int
    anthropic_key_set: bool
    github_token_set: bool
    workspace: str


Listener = Callable[[JobEvent], None]
Unsubscribe = Callable[[], None]


class JobRunner(Protocol):
    """Starts jobs, keeps their history and tells listeners what happens.

    `exclusive` jobs run one at a time, in the order they were submitted, because they use Docker.
    Listeners are called from the runner's own threads.
    """

    def machine(self) -> Machine: ...

    def submit(self, spec: JobSpec) -> JobRecord: ...

    def cancel(self, job_id: str) -> None: ...

    def jobs(self) -> tuple[JobRecord, ...]: ...

    def job(self, job_id: str) -> JobRecord: ...

    def log(self, job_id: str, *, tail: int | None = None) -> tuple[str, ...]: ...

    def subscribe(self, listener: Listener) -> Unsubscribe: ...

    def close(self) -> None: ...
