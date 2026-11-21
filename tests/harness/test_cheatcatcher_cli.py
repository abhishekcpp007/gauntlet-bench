"""`gauntlet cheatcatcher` hands its arguments to Cheat Catcher's own CLI. No Docker."""

import os

from gauntlet.cheatcatcher.cli import EXIT_CODES
from gauntlet.cheatcatcher.cli import main as cheatcatcher
from gauntlet.harness.cli import main

GUTTED_ASSERT = "--- a/tests/test_x.py\n+++ b/tests/test_x.py\n@@ -1 +1 @@\n-    assert x == 1\n+    pass\n"


def test_rules_prints_and_exits_like_cheatcatcher(capsys):
    assert main(["cheatcatcher", "rules"]) == os.EX_OK
    ours = capsys.readouterr().out
    assert cheatcatcher(["rules"]) == os.EX_OK
    assert ours == capsys.readouterr().out


def test_scan_exits_like_cheatcatcher(tmp_path, capsys):
    patch = tmp_path / "p.diff"
    patch.write_text(GUTTED_ASSERT)
    scan = ["scan", "--patch", str(patch), "--json"]
    assert main(["cheatcatcher", *scan]) == EXIT_CODES["suspicious"]
    ours = capsys.readouterr().out
    assert cheatcatcher(scan) == EXIT_CODES["suspicious"]
    assert ours == capsys.readouterr().out
    assert main(["cheatcatcher", "scan"]) == cheatcatcher(["scan"]) == os.EX_USAGE
