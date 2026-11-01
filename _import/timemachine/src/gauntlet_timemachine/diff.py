"""Line two runs up and find where they stopped doing the same thing."""

from __future__ import annotations

from typing import Any

from gauntlet_sandbox import Step, Trajectory
from pydantic import BaseModel, Field

_KEYS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # kind: (action fields, observation fields)
    "exec": (("command",), ("exit_code", "stdout", "stderr", "timed_out")),
    "write_file": (("path", "content"), ()),
    "read_file": (("path",), ("ok", "content")),
    "put_archive": (("dest", "sha256"), ()),
    "snapshot": (("label",), ()),
}


def step_key(step: Step) -> tuple[Any, ...]:
    kind = step.action.get("type", "")
    action_fields, obs_fields = _KEYS.get(kind, ((), ()))
    return (
        kind,
        *(step.action.get(f) for f in action_fields),
        *(step.observation.get(f) for f in obs_fields),
    )


def summarize(step: Step) -> str:
    a, o = step.action, step.observation
    kind = a.get("type")
    if kind == "exec":
        status = "TIMEOUT" if o.get("timed_out") else f"exit {o.get('exit_code')}"
        return f"$ {a.get('command')}  -> {status}"
    if kind == "write_file":
        return f"write {a.get('path')} ({o.get('size', '?')} bytes)"
    if kind == "read_file":
        return f"read {a.get('path')}" + ("" if o.get("ok", True) else " (not found)")
    if kind == "put_archive":
        return f"unpack {a.get('size', '?')} bytes into {a.get('dest')}"
    if kind == "snapshot":
        return f"snapshot {o.get('image', '')}".rstrip()
    return str(kind)


class StepSummary(BaseModel):
    index: int
    kind: str
    summary: str


class TrajectoryDiff(BaseModel):
    a_steps: int
    b_steps: int
    common_prefix: int
    differing_fields: list[str] = Field(default_factory=list)
    a_rest: list[StepSummary] = Field(default_factory=list)
    b_rest: list[StepSummary] = Field(default_factory=list)

    @property
    def identical(self) -> bool:
        return self.common_prefix == self.a_steps == self.b_steps


def _rest(steps: list[Step]) -> list[StepSummary]:
    return [StepSummary(index=s.index, kind=s.action.get("type", ""), summary=summarize(s)) for s in steps]


def _fields_that_differ(a: Step, b: Step) -> list[str]:
    if a.action.get("type") != b.action.get("type"):
        return ["type"]
    kind = a.action.get("type", "")
    action_fields, obs_fields = _KEYS.get(kind, ((), ()))
    out = [f"action.{f}" for f in action_fields if a.action.get(f) != b.action.get(f)]
    out += [f"observation.{f}" for f in obs_fields if a.observation.get(f) != b.observation.get(f)]
    return out


def diff(a: Trajectory, b: Trajectory) -> TrajectoryDiff:
    prefix = 0
    for sa, sb in zip(a.steps, b.steps, strict=False):
        if step_key(sa) != step_key(sb):
            break
        prefix += 1
    fields = []
    if prefix < len(a.steps) and prefix < len(b.steps):
        fields = _fields_that_differ(a.steps[prefix], b.steps[prefix])
    return TrajectoryDiff(
        a_steps=len(a.steps),
        b_steps=len(b.steps),
        common_prefix=prefix,
        differing_fields=fields,
        a_rest=_rest(a.steps[prefix:]),
        b_rest=_rest(b.steps[prefix:]),
    )
