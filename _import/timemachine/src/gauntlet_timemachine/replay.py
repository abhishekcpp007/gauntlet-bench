"""Re-run a recorded trajectory in a fresh sandbox, or stop partway and hand over the live box."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from docker.errors import APIError
from gauntlet_sandbox import Sandbox, SandboxConfig, Step, Trajectory
from pydantic import BaseModel, Field

# which observation fields have to match for a step to count as reproduced
COMPARED_FIELDS: dict[str, tuple[str, ...]] = {
    "exec": ("exit_code", "stdout", "stderr", "timed_out"),
    "write_file": ("ok", "size"),
    "read_file": ("ok", "size", "content"),
    "put_archive": ("ok",),
    "snapshot": (),
}


class ReplayError(RuntimeError):
    """A step can't be replayed, like an archive whose blob was never saved."""


class Divergence(BaseModel):
    step: int
    field: str
    original: Any
    replayed: Any


class ReplayReport(BaseModel):
    source: str
    steps_replayed: int = 0
    divergences: list[Divergence] = Field(default_factory=list)

    @property
    def deterministic(self) -> bool:
        return not self.divergences


def _config(traj: Trajectory, image: str | None) -> SandboxConfig:
    cfg = SandboxConfig(**traj.header.config)
    return cfg.model_copy(update={"image": image}) if image else cfg


def _check_upto(traj: Trajectory, upto: int | None, name: str) -> list[Step]:
    if upto is None:
        return list(traj.steps)
    if not 0 <= upto <= len(traj.steps):
        raise ValueError(f"{name} must be between 0 and {len(traj.steps)}, got {upto}")
    return traj.steps[:upto]


def apply_step(sb: Sandbox, traj: Trajectory, step: Step) -> dict[str, Any]:
    """Perform one recorded action on `sb` and return the fresh observation."""
    a = step.action
    kind = a.get("type")
    if kind == "exec":
        return sb.exec(
            a["command"], timeout=a.get("timeout"), workdir=a.get("workdir"), env=a.get("env")
        ).model_dump()

    if kind == "write_file":
        content = a.get("content", "")
        data = base64.b64decode(content) if a.get("encoding") == "base64" else content.encode("utf-8")
        sb.write_file(a["path"], data, mode=a.get("mode", 0o644))
        return {"ok": True, "size": len(data)}

    if kind == "read_file":
        try:
            sb.read_file(a["path"])
        except FileNotFoundError:
            return {"ok": False, "error": "not found"}
        if sb.trajectory is not None:
            return dict(sb.trajectory.steps[-1].observation)
        return {"ok": True}

    if kind == "put_archive":
        digest = a.get("sha256")
        if not digest:
            raise ReplayError(
                f"step {step.index}: this archive wasn't saved. It was recorded without a trajectory "
                "file, or by a gauntlet-sandbox older than blob support."
            )
        try:
            data = traj.load_blob(digest)
        except FileNotFoundError as e:
            raise ReplayError(f"step {step.index}: {e}. Keep the .blobs folder next to the .jsonl") from e
        sb.put_archive(a["dest"], data)
        return {"ok": True}

    if kind == "snapshot":
        ref = sb.snapshot(label=a.get("label"))
        # the filesystem is what matters for a replay, so don't leave a pile of images behind
        try:
            sb.client.images.remove(ref)
        except APIError:
            pass
        return {"ok": True, "image": ref}

    raise ReplayError(f"step {step.index}: don't know how to replay action type {kind!r}")


def compare(step: Step, replayed: dict[str, Any]) -> list[Divergence]:
    kind = step.action.get("type", "")
    out = []
    for field in COMPARED_FIELDS.get(kind, ()):
        before, after = step.observation.get(field), replayed.get(field)
        if before != after:
            out.append(Divergence(step=step.index, field=field, original=before, replayed=after))
    return out


def replay(
    traj: Trajectory,
    *,
    upto: int | None = None,
    image: str | None = None,
    trajectory_path: str | Path | None = None,
) -> ReplayReport:
    """Re-run steps 0..upto-1 (all of them by default) and report every observation that changed."""
    steps = _check_upto(traj, upto, "upto")
    report = ReplayReport(source=traj.header.sandbox_id)
    meta = {"replay_of": traj.header.sandbox_id}
    with Sandbox(_config(traj, image), trajectory_path=trajectory_path, metadata=meta) as sb:
        for step in steps:
            observed = apply_step(sb, traj, step)
            report.divergences.extend(compare(step, observed))
            report.steps_replayed += 1
    return report


def branch(
    traj: Trajectory,
    at: int,
    *,
    image: str | None = None,
    trajectory_path: str | Path | None = None,
) -> Sandbox:
    """Replay the steps before `at` and return the live sandbox, ready for a different step `at`.

    The caller owns the sandbox and has to close it. Its trajectory holds the replayed
    steps too, so it reads as one complete run that forked off the original.
    """
    steps = _check_upto(traj, at, "at")
    meta = {**traj.header.metadata, "branched_from": traj.header.sandbox_id, "branched_at": at}
    sb = Sandbox(_config(traj, image), trajectory_path=trajectory_path, metadata=meta).start()
    try:
        for step in steps:
            apply_step(sb, traj, step)
    except Exception:
        sb.close()
        raise
    return sb
