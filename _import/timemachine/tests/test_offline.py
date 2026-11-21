"""Viewer and diff tests on hand-made trajectories. No Docker needed."""

import json
import re

from gauntlet_sandbox import Trajectory, TrajectoryHeader

from gauntlet_timemachine import diff, render_html
from gauntlet_timemachine.cli import main

from .conftest import exec_step, make_traj


def _embedded(page: str) -> dict:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', page, re.S)
    assert m, "no embedded data block"
    return json.loads(m.group(1))


def test_render_roundtrips_data():
    traj = make_traj(
        exec_step("echo hi", stdout="hi\n"),
        (
            {"type": "write_file", "path": "/w/a.py", "content": "x = 1\n", "encoding": "utf-8"},
            {"ok": True, "size": 6},
        ),
        exec_step("false", exit_code=1),
    )
    page = render_html(traj, title="Demo run")
    assert page.startswith("<!doctype html>")
    assert "<title>Demo run</title>" in page
    data = _embedded(page)
    assert [s["action"]["type"] for s in data["steps"]] == ["exec", "write_file", "exec"]
    assert data["steps"][0]["observation"]["stdout"] == "hi\n"
    assert data["header"]["sandbox_id"] == "abc123"


def test_hostile_output_cant_break_out():
    nasty = "</script><script>alert(1)</script> &   <!--"
    traj = make_traj(exec_step("cat evil", stdout=nasty))
    page = render_html(traj, title="<b>x</b>")
    # exactly two closing tags: the data block and the app script
    assert page.count("</script>") == 2
    assert "<title>&lt;b&gt;x&lt;/b&gt;</title>" in page
    assert _embedded(page)["steps"][0]["observation"]["stdout"] == nasty


def test_annotations_are_embedded():
    traj = make_traj(exec_step("ls"), exec_step("rm tests/test_x.py"))
    page = render_html(traj, annotations={1: ["deleted a test file"]})
    assert _embedded(page)["annotations"] == {"1": ["deleted a test file"]}


def test_no_external_requests():
    page = render_html(make_traj(exec_step("ls")))
    assert not re.search(r"""(src|href)=["']https?://""", page)
    assert "@import" not in page


def test_empty_trajectory_renders():
    traj = Trajectory(TrajectoryHeader(sandbox_id="e", image="x", created_at=0))
    assert _embedded(render_html(traj))["steps"] == []


def test_diff_finds_the_split():
    a = make_traj(exec_step("ls", "a\n"), exec_step("python t.py", exit_code=1), exec_step("cat x"))
    b = make_traj(exec_step("ls", "a\n"), exec_step("python t.py", exit_code=0))
    d = diff(a, b)
    assert d.common_prefix == 1
    assert d.differing_fields == ["observation.exit_code"]
    assert [s.index for s in d.a_rest] == [1, 2]
    assert d.b_rest[0].summary == "$ python t.py  -> exit 0"
    assert not d.identical


def test_diff_identical_and_type_change():
    a = make_traj(exec_step("ls"))
    assert diff(a, make_traj(exec_step("ls"))).identical
    other = make_traj(({"type": "read_file", "path": "/x"}, {"ok": False, "error": "not found"}))
    d = diff(a, other)
    assert d.common_prefix == 0 and d.differing_fields == ["type"]
    assert d.b_rest[0].summary == "read /x (not found)"


def test_cli_view_and_diff(tmp_path, capsys):
    path = tmp_path / "run.jsonl"
    traj = Trajectory(TrajectoryHeader(sandbox_id="s1", image="img", created_at=0), path=path)
    a, o = exec_step("echo hi", "hi\n")
    traj.record(a, o)

    assert main(["view", str(path)]) == 0
    assert (tmp_path / "run.html").exists()

    assert main(["diff", str(path), str(path)]) == 0
    assert "identical" in capsys.readouterr().out
