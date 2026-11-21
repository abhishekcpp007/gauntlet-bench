"""Runs Workbench jobs as `gauntlet` processes, one queue for Docker and a log for each job.

`SubprocessJobRunner` implements `JobRunner` from `jobtypes`. Each step of a job runs
`python -m gauntlet.harness.cli <argv...>` as its own process: no shell, the parent's
environment plus `PYTHONUNBUFFERED=1`, and the workspace as its working folder. Its stdout and
stderr are read line by line on two threads, and every line goes to the job's log file and to
listeners as a `line` event.

    jobs/<id>/job.json   the record, replaced atomically on every change
    jobs/<id>/log.txt    every line the job printed, as it printed it

Exclusive jobs (the ones that use Docker) run one at a time in the order they came in. Others
start at once. Cancel takes a queued job off the queue. A running one gets an interrupt, so the
harness can close its sandboxes, then a terminate after `interrupt_grace` seconds and a kill
after `terminate_grace` more. A job left queued or running by an earlier session is marked
failed when the runner starts, never resumed.

Portability: on POSIX each step starts in a new session, its own process group, and every
signal goes to the whole group, so the harness's own children stop too. On Windows it starts
in a new process group, the interrupt is CTRL_BREAK_EVENT, and terminate and kill reach only
the direct child.

Everything that touches the OS can be swapped: `start` makes the processes, `clock` gives
timestamps, `environ` is the parent environment and `machine` checks the machine.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import site
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, replace
from itertools import count
from pathlib import Path
from typing import IO, Any, Protocol

import gauntlet

from .jobtypes import (
    FINISHED,
    SUCCESS,
    JobEvent,
    JobNotFound,
    JobRecord,
    JobSpec,
    JobState,
    Listener,
    Machine,
    Output,
    Step,
    Stream,
    Unsubscribe,
)
from .machine import inspect_machine
from .workspace import Workspace

log = logging.getLogger(__name__)

HARNESS_MODULE = "gauntlet.harness.cli"
JOB_FILE = "job.json"
LOG_FILE = "log.txt"
LOG_ENCODING = "utf-8"
INTERRUPT_GRACE_SECONDS = 20.0
TERMINATE_GRACE_SECONDS = 10.0
CLOSE_TIMEOUT_SECONDS = 5.0
KILL_WAIT_SECONDS = 1.0
TAIL_BLOCK_BYTES = 64 * 1024
ID_TIME_FORMAT = "%Y%m%d-%H%M%S"
ID_COUNTER_WIDTH = 3
INTERRUPTED = "the viewer closed while this job was running"
UNFINISHED: frozenset[JobState] = frozenset({"queued", "running"})


class RunnerClosed(RuntimeError):
    """The runner was closed and takes no more jobs."""


class Process(Protocol):
    """A started step. `wait(timeout)` raises `subprocess.TimeoutExpired` when time runs out."""

    @property
    def stdout(self) -> IO[bytes]: ...

    @property
    def stderr(self) -> IO[bytes]: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def interrupt(self) -> None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


ProcessFactory = Callable[[Sequence[str], Mapping[str, str], Path], Process]
Clock = Callable[[], float]


class PopenProcess:
    """A real child process in its own process group, signalled as a group."""

    def __init__(self, argv: Sequence[str], env: Mapping[str, str], cwd: Path) -> None:
        group: dict[str, Any] = (
            {"start_new_session": True}
            if os.name == "posix"
            else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}  # type: ignore[attr-defined]  # Windows only
        )
        self._popen = subprocess.Popen(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=dict(env),
            cwd=cwd,
            **group,
        )

    @property
    def stdout(self) -> IO[bytes]:
        assert self._popen.stdout is not None
        return self._popen.stdout

    @property
    def stderr(self) -> IO[bytes]:
        assert self._popen.stderr is not None
        return self._popen.stderr

    def wait(self, timeout: float | None = None) -> int:
        return self._popen.wait(timeout)

    def _signal_group(self, number: int) -> None:
        with suppress(ProcessLookupError):
            os.killpg(self._popen.pid, number)

    def interrupt(self) -> None:
        if os.name == "posix":
            self._signal_group(signal.SIGINT)
        else:
            self._popen.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]  # Windows only

    def terminate(self) -> None:
        if os.name == "posix":
            self._signal_group(signal.SIGTERM)
        else:
            self._popen.terminate()

    def kill(self) -> None:
        if os.name == "posix":
            self._signal_group(signal.SIGKILL)
        else:
            self._popen.kill()


def source_root() -> Path | None:
    """The folder holding this `gauntlet` package when it runs from a source tree, or None when
    it's installed in site-packages, where every Python finds it anyway."""
    root = Path(gauntlet.__file__).resolve().parent.parent
    sites = [*site.getsitepackages(), site.getusersitepackages()]
    installed = {Path(p).resolve() for p in sites if p}
    return None if root in installed else root


def child_environment(base: Mapping[str, str], root: Path | None, cwd: Path | None = None) -> dict[str, str]:
    """The parent's environment, unbuffered, able to import this checkout from any folder.

    Relative `PYTHONPATH` entries are made absolute against `cwd` (the parent's folder), since
    the child runs in the workspace, and `root` goes first when it isn't there already.
    """
    env = dict(base)
    env["PYTHONUNBUFFERED"] = "1"
    here = cwd or Path.cwd()
    entries = [str((here / p).resolve()) for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    if root is not None and str(root) not in entries:
        entries.insert(0, str(root))
    if entries:
        env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def format_job_id(timestamp: float, counter: int) -> str:
    """`20261122-143005-001`: UTC to the second, then a counter, so ids sort by time."""
    return f"{time.strftime(ID_TIME_FORMAT, time.gmtime(timestamp))}-{counter:0{ID_COUNTER_WIDTH}d}"


def record_to_json(record: JobRecord) -> dict[str, Any]:
    return asdict(record)


def record_from_json(raw: Mapping[str, Any]) -> JobRecord:
    """A record back from `job.json`. Fields a later version added are ignored."""
    spec = raw["spec"]
    steps = tuple(
        Step(title=s["title"], argv=tuple(s["argv"]), ok_codes=tuple(s.get("ok_codes", (SUCCESS,))))
        for s in spec["steps"]
    )
    outputs = tuple(
        Output(kind=o["kind"], path=o["path"], label=o["label"], episode_id=o.get("episode_id"))
        for o in spec.get("outputs", ())
    )
    return JobRecord(
        id=raw["id"],
        spec=JobSpec(
            action=spec["action"],
            title=spec["title"],
            steps=steps,
            needs=tuple(spec.get("needs", ())),
            outputs=outputs,
            exclusive=spec.get("exclusive", True),
        ),
        state=raw["state"],
        created_at=raw["created_at"],
        log_path=raw["log_path"],
        step_index=raw.get("step_index", 0),
        started_at=raw.get("started_at"),
        finished_at=raw.get("finished_at"),
        exit_code=raw.get("exit_code"),
        error=raw.get("error"),
    )


def write_atomic(path: Path, text: str) -> None:
    """Write to a temporary file next to `path`, then move it into place."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding=LOG_ENCODING) as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def tail_lines(path: Path, n: int) -> tuple[str, ...]:
    """The last `n` lines of a file, reading backwards a block at a time."""
    if n <= 0 or not path.is_file():
        return ()
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        data = b""
        while end > 0 and data.count(b"\n") <= n:
            size = min(TAIL_BLOCK_BYTES, end)
            end -= size
            f.seek(end)
            data = f.read(size) + data
    lines = data.decode(LOG_ENCODING, errors="replace").splitlines()
    return tuple(lines[-n:])


class _JobLog:
    """The job's log file, shared by its reader threads."""

    def __init__(self, path: Path) -> None:
        self._lock = threading.Lock()
        self._file: IO[str] | None = path.open("a", encoding=LOG_ENCODING, errors="replace")

    def write(self, line: str) -> None:
        with self._lock:
            if self._file is not None:
                self._file.write(line + "\n")
                self._file.flush()

    def close(self) -> None:
        with self._lock:
            if self._file is not None:
                self._file.close()
                self._file = None


class SubprocessJobRunner:
    """Runs jobs as `gauntlet` processes. See the module docstring for how and where."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        python: str = sys.executable,
        start: ProcessFactory = PopenProcess,
        clock: Clock = time.time,
        environ: Mapping[str, str] | None = None,
        machine: Callable[[], Machine] | None = None,
        interrupt_grace: float = INTERRUPT_GRACE_SECONDS,
        terminate_grace: float = TERMINATE_GRACE_SECONDS,
        close_timeout: float = CLOSE_TIMEOUT_SECONDS,
    ) -> None:
        self._workspace = workspace
        self._python = python
        self._start = start
        self._clock = clock
        self._environ = os.environ if environ is None else environ
        self._machine = machine or (lambda: inspect_machine(workspace))
        self._interrupt_grace = interrupt_grace
        self._terminate_grace = terminate_grace
        self._close_timeout = close_timeout
        self._lock = threading.RLock()
        self._records: dict[str, JobRecord] = {}
        self._queue: deque[str] = deque()
        self._exclusive: str | None = None
        self._procs: dict[str, Process] = {}
        self._logs: dict[str, _JobLog] = {}
        self._cancelling: set[str] = set()
        self._threads: list[threading.Thread] = []
        self._listeners: list[Listener] = []
        self._closed = False
        self.load_warnings: tuple[str, ...] = self._load_history()

    # ------------------------------------------------------------------ JobRunner

    def machine(self) -> Machine:
        return self._machine()

    def submit(self, spec: JobSpec) -> JobRecord:
        """Record the job and start it, or queue it behind the running exclusive job."""
        with self._lock:
            if self._closed:
                raise RunnerClosed("the runner is closed and takes no more jobs")
            job_id, folder = self._new_job_dir()
            log_path = folder / LOG_FILE
            log_path.touch()
            record = JobRecord(
                id=job_id, spec=spec, state="queued", created_at=self._clock(), log_path=str(log_path)
            )
            self._records[job_id] = record
            self._save(record)
            if spec.exclusive:
                self._queue.append(job_id)
        self._emit(JobEvent("state", record))
        with self._lock:
            if spec.exclusive:
                self._start_next()
            else:
                self._spawn(self._run_job, job_id)
        return record

    def cancel(self, job_id: str) -> None:
        """Take a queued job off the queue, or stop a running one. A finished job stays as it is."""
        with self._lock:
            record = self.job(job_id)
            if record.state in FINISHED or job_id in self._cancelling:
                return
            if job_id in self._queue:
                self._queue.remove(job_id)
                event = self._finish(job_id, "cancelled")
            else:
                self._cancelling.add(job_id)
                event = None
                proc = self._procs.get(job_id)
                if proc is not None:
                    self._spawn(self._stop, job_id, proc)
        if event is not None:
            self._emit(event)

    def jobs(self) -> tuple[JobRecord, ...]:
        """Every job, newest first."""
        with self._lock:
            return tuple(sorted(self._records.values(), key=lambda r: r.id, reverse=True))

    def job(self, job_id: str) -> JobRecord:
        with self._lock:
            try:
                return self._records[job_id]
            except KeyError:
                raise JobNotFound(f"no job {job_id!r}") from None

    def log(self, job_id: str, *, tail: int | None = None) -> tuple[str, ...]:
        """The job's log lines, or only the last `tail` of them, without reading the whole file."""
        path = Path(self.job(job_id).log_path)
        if tail is not None:
            return tail_lines(path, tail)
        if not path.is_file():
            return ()
        return tuple(path.read_text(encoding=LOG_ENCODING, errors="replace").splitlines())

    def subscribe(self, listener: Listener) -> Unsubscribe:
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe

    def close(self) -> None:
        """Take no more jobs, cancel the rest, and wait at most `close_timeout` (plus a moment to
        kill what's left) for every thread."""
        events = []
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while self._queue:
                events.append(self._finish(self._queue.popleft(), "cancelled"))
            live = [r.id for r in self._records.values() if r.state in UNFINISHED]
        for event in events:
            self._emit(event)
        for job_id in live:
            self.cancel(job_id)
        deadline = time.monotonic() + self._close_timeout
        self._join(deadline)
        with self._lock:
            left = list(self._procs.values())
        for proc in left:
            with suppress(OSError):
                proc.kill()
        self._join(time.monotonic() + KILL_WAIT_SECONDS)

    # ------------------------------------------------------------------ inside

    def _join(self, deadline: float) -> None:
        with self._lock:
            threads = list(self._threads)
        for thread in threads:
            thread.join(max(0.0, deadline - time.monotonic()))

    def _spawn(self, target: Callable[..., None], *args: Any) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]
            self._threads.append(thread)
        thread.start()

    def _start_next(self) -> None:
        if self._exclusive is None and self._queue and not self._closed:
            job_id = self._queue.popleft()
            self._exclusive = job_id
            self._spawn(self._run_job, job_id)

    def _new_job_dir(self) -> tuple[str, Path]:
        root = self._workspace.jobs_root()
        stamp = self._clock()
        for n in count(1):
            job_id = format_job_id(stamp, n)
            try:
                (root / job_id).mkdir()
            except FileExistsError:
                continue
            return job_id, root / job_id
        raise AssertionError("unreachable")

    def _save(self, record: JobRecord) -> None:
        folder = Path(record.log_path).parent
        write_atomic(folder / JOB_FILE, json.dumps(record_to_json(record), indent=1))

    def _update(self, job_id: str, **changes: Any) -> JobRecord:
        with self._lock:
            record = replace(self._records[job_id], **changes)
            self._records[job_id] = record
            self._save(record)
            return record

    def _finish(
        self, job_id: str, state: JobState, *, exit_code: int | None = None, error: str | None = None
    ) -> JobEvent:
        with self._lock:
            self._cancelling.discard(job_id)
            record = self._update(
                job_id, state=state, finished_at=self._clock(), exit_code=exit_code, error=error
            )
        return JobEvent("state", record)

    def _emit(self, event: JobEvent) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(event)
            except Exception:
                log.exception("a job listener failed on %s", event.kind)

    def _line(self, job_id: str, text: str, stream: Stream | None) -> None:
        with self._lock:
            job_log = self._logs.get(job_id)
            record = self._records[job_id]
        if job_log is not None:
            job_log.write(text)
        self._emit(JobEvent("line", record, text=text, stream=stream))

    def _read(self, job_id: str, pipe: IO[bytes], stream: Stream) -> None:
        try:
            for raw in iter(pipe.readline, b""):
                self._line(job_id, raw.decode(LOG_ENCODING, errors="replace").rstrip("\r\n"), stream)
        finally:
            with suppress(OSError):
                pipe.close()

    def _run_job(self, job_id: str) -> None:
        record = self.job(job_id)
        job_log = _JobLog(Path(record.log_path))
        with self._lock:
            self._logs[job_id] = job_log
        try:
            event = self._run_steps(job_id, record.spec)
        except Exception as e:  # a bug here must not leave the job running forever
            log.exception("job %s crashed", job_id)
            event = self._finish(job_id, "failed", error=f"the runner failed: {type(e).__name__}: {e}")
        finally:
            job_log.close()
            with self._lock:
                self._logs.pop(job_id, None)
        self._emit(event)
        with self._lock:
            if self._exclusive == job_id:
                self._exclusive = None
                self._start_next()

    def _run_steps(self, job_id: str, spec: JobSpec) -> JobEvent:
        env = child_environment(self._environ, source_root())
        cwd = self._workspace.root
        cwd.mkdir(parents=True, exist_ok=True)
        code: int | None = None
        for index, step in enumerate(spec.steps):
            with self._lock:
                if job_id in self._cancelling:
                    return self._finish(job_id, "cancelled", exit_code=code)
                first = self._records[job_id].state != "running"
                record = self._update(
                    job_id,
                    state="running",
                    step_index=index,
                    started_at=self._records[job_id].started_at or self._clock(),
                )
            if first:
                self._emit(JobEvent("state", record))
            self._emit(JobEvent("step", record, text=step.title))
            try:
                proc = self._start([self._python, "-m", HARNESS_MODULE, *step.argv], env, cwd)
            except OSError as e:
                return self._finish(job_id, "failed", error=f"couldn't start {step.title.lower()}: {e}")
            with self._lock:
                self._procs[job_id] = proc
                stop_now = job_id in self._cancelling
            if stop_now:
                self._spawn(self._stop, job_id, proc)
            readers = [
                threading.Thread(target=self._read, args=(job_id, proc.stdout, "out"), daemon=True),
                threading.Thread(target=self._read, args=(job_id, proc.stderr, "err"), daemon=True),
            ]
            for reader in readers:
                reader.start()
            code = proc.wait()
            for reader in readers:
                reader.join()
            with self._lock:
                self._procs.pop(job_id, None)
                if job_id in self._cancelling:
                    return self._finish(job_id, "cancelled", exit_code=code)
            if code not in step.ok_codes:
                return self._finish(
                    job_id, "failed", exit_code=code, error=f"{step.title} exited with code {code}"
                )
        return self._finish(job_id, "succeeded", exit_code=code)

    def _stop(self, job_id: str, proc: Process) -> None:
        escalation = (
            (
                proc.interrupt,
                self._interrupt_grace,
                "Sent an interrupt so the harness can close its sandboxes.",
            ),
            (proc.terminate, self._terminate_grace, "Still running, so sent a terminate."),
        )
        for send, grace, note in escalation:
            self._line(job_id, note, None)
            with suppress(OSError):
                send()
            try:
                proc.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue
        self._line(job_id, "Still running, so killed it.", None)
        with suppress(OSError):
            proc.kill()

    def _load_history(self) -> tuple[str, ...]:
        warnings = []
        for folder in sorted(p for p in self._workspace.jobs_root().iterdir() if p.is_dir()):
            path = folder / JOB_FILE
            if not path.is_file():
                continue
            try:
                record = record_from_json(json.loads(path.read_text(encoding=LOG_ENCODING)))
            except (OSError, ValueError, KeyError, TypeError) as e:
                warnings.append(f"Skipped {path}: it isn't a job record ({type(e).__name__}: {e}).")
                continue
            if record.state in UNFINISHED:
                record = replace(
                    record, state="failed", error=INTERRUPTED, finished_at=_last_change(folder, record)
                )
                self._save(record)
            self._records[record.id] = record
        return tuple(warnings)


def _last_change(folder: Path, record: JobRecord) -> float:
    """When an interrupted job last showed signs of life: its log's or its record's last write."""
    times = [p.stat().st_mtime for p in (folder / LOG_FILE, folder / JOB_FILE) if p.exists()]
    return max(times, default=record.started_at or record.created_at)
