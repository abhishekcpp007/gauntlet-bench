"""Record a small but realistic agent run, then render it with the viewer.

    uv run python examples/record_demo.py

Writes examples/demo_run.jsonl (gitignored) and examples/sample.html.
"""

from pathlib import Path

from gauntlet_sandbox import Sandbox, SandboxConfig, Trajectory

from gauntlet_timemachine import render_html

HERE = Path(__file__).parent
RUN = HERE / "demo_run.jsonl"

TEST = """\
from slugify import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_punctuation():
    assert slugify("Ready, set... go!") == "ready-set-go"


def test_spaces():
    assert slugify("  lots   of   space  ") == "lots-of-space"
"""

FIRST_TRY = """\
def slugify(text):
    return text.lower().replace(" ", "-")
"""

SECOND_TRY = """\
import re


def slugify(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return "-".join(words)
"""

RUNNER = """\
import sys
import test_slugify as t

failed = 0
for name in sorted(n for n in dir(t) if n.startswith("test_")):
    try:
        getattr(t, name)()
        print("PASS", name)
    except AssertionError:
        print("FAIL", name)
        failed += 1
sys.exit(1 if failed else 0)
"""

config = SandboxConfig(image="python:3.12-slim")
with Sandbox(config, trajectory_path=RUN, metadata={"task": "slugify"}) as sb:
    sb.write_file("test_slugify.py", TEST)
    sb.write_file("run_tests.py", RUNNER)
    sb.exec("ls")
    sb.read_file("test_slugify.py")
    sb.write_file("slugify.py", FIRST_TRY)
    sb.exec("python -c 'from slugify import slugify; print(slugify(\"Ready, set... go!\"))'")
    sb.exec("python run_tests.py")
    sb.exec("sleep 5", timeout=1)
    sb.client.images.remove(sb.snapshot(label="before second try"))  # keep the record, not the image
    sb.write_file("slugify.py", SECOND_TRY)
    sb.exec("python run_tests.py")

traj = Trajectory.load(RUN)
annotations = {7: ["Agent ran a command that hung and got killed by the 1s timeout"]}
page = render_html(traj, title="slugify: two attempts", annotations=annotations)
(HERE / "sample.html").write_text(page, encoding="utf-8")
print(f"{len(traj)} steps, wrote {HERE / 'sample.html'}")
