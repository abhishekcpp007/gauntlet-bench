"""The CLI's shared helpers. No Docker."""

from gauntlet.harness.cli import _out


def test_out_creates_the_missing_folders(tmp_path):
    out = _out(str(tmp_path / "fresh" / "dir" / "prs.jsonl"))
    assert out.parent.is_dir()
