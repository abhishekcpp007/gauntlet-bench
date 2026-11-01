"""Command line: `timemachine view|replay|branch|diff`."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from gauntlet_sandbox import SandboxError, Trajectory

from . import __version__
from .diff import diff
from .replay import ReplayError, branch, replay
from .viewer import render_html


def _short(value: object, n: int = 200) -> str:
    text = repr(value)
    return text if len(text) <= n else text[:n] + "..."


def cmd_view(args: argparse.Namespace) -> int:
    traj = Trajectory.load(args.file)
    out = Path(args.output) if args.output else Path(args.file).with_suffix(".html")
    out.write_text(render_html(traj, title=args.title), encoding="utf-8")
    print(f"wrote {out}")
    if args.open:
        webbrowser.open(out.resolve().as_uri())
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    traj = Trajectory.load(args.file)
    report = replay(traj, upto=args.upto, image=args.image, trajectory_path=args.record)
    for d in report.divergences:
        print(f"step {d.step} {d.field} changed")
        print(f"   was: {_short(d.original)}")
        print(f"   now: {_short(d.replayed)}")
    verdict = "identical" if report.deterministic else f"{len(report.divergences)} divergence(s)"
    print(f"replayed {report.steps_replayed} step(s): {verdict}")
    return 0 if report.deterministic else 1


def cmd_branch(args: argparse.Namespace) -> int:
    traj = Trajectory.load(args.file)
    sb = branch(traj, args.at, image=args.image, trajectory_path=args.record)
    try:
        print(f"branched from {traj.header.sandbox_id} at step {args.at}, replayed {args.at} step(s).")
        print(f"you're in sandbox {sb.id} on {sb.config.image}. Ctrl-D to leave.")
        while True:
            try:
                line = input("branch$ ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            res = sb.exec(line)
            sys.stdout.write(res.stdout)
            sys.stderr.write(res.stderr)
            if res.timed_out:
                print("[timed out]", file=sys.stderr)
            elif res.exit_code:
                print(f"[exit {res.exit_code}]", file=sys.stderr)
    finally:
        sb.close()
    if args.record:
        print(f"new trajectory saved to {args.record}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    a, b = Trajectory.load(args.a), Trajectory.load(args.b)
    d = diff(a, b)
    if d.identical:
        print(f"identical, {d.a_steps} step(s)")
        return 0
    print(f"same for the first {d.common_prefix} step(s), then they split")
    if d.differing_fields:
        print(f"at step {d.common_prefix}: {', '.join(d.differing_fields)} differ")
    for name, rest in (("A", d.a_rest), ("B", d.b_rest)):
        print(f"\n{name} ({args.a if name == 'A' else args.b}), {len(rest)} more step(s):")
        for s in rest[: args.max]:
            print(f"  #{s.index} {s.summary[:120]}")
        if len(rest) > args.max:
            print(f"  ... {len(rest) - args.max} more")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="timemachine", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("view", help="render a trajectory as a standalone HTML page")
    p.add_argument("file")
    p.add_argument("-o", "--output", help="defaults to the trajectory name with .html")
    p.add_argument("--title")
    p.add_argument("--open", action="store_true", help="open it in your browser")
    p.set_defaults(fn=cmd_view)

    p = sub.add_parser("replay", help="re-run a trajectory and report anything that changed")
    p.add_argument("file")
    p.add_argument("--upto", type=int, help="only replay steps before this index")
    p.add_argument("--image", help="run on a different image than the original")
    p.add_argument("--record", help="save the replay's own trajectory here")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("branch", help="rewind to a step and take over from there")
    p.add_argument("file")
    p.add_argument("--at", type=int, required=True, help="replay steps before this one, then hand over")
    p.add_argument("--image")
    p.add_argument("--record", help="save the branched trajectory here")
    p.set_defaults(fn=cmd_branch)

    p = sub.add_parser("diff", help="find where two runs split")
    p.add_argument("a")
    p.add_argument("b")
    p.add_argument("--max", type=int, default=20, help="max steps to list per side")
    p.set_defaults(fn=cmd_diff)

    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (ReplayError, SandboxError, ValueError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
