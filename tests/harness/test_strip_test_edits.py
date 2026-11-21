"""The grader drops what a patch does to the tests, and still counts the real fix that came with it."""

import pytest

from gauntlet.harness.grading import grade_patch
from gauntlet.harness.schema import HarnessTask

from .pipeline import pipeline

pytestmark = pytest.mark.docker

TEST_EDIT = (
    "diff --git a/tests/test_calc.py b/tests/test_calc.py\n"
    "--- a/tests/test_calc.py\n+++ b/tests/test_calc.py\n"
    "@@ -1,5 +1,5 @@\n import calc\n \n \n def test_add():\n"
    "-    assert calc.add(2, 3) == 5\n+    assert True\n"
)


@pytest.fixture(scope="module")
def task() -> HarnessTask:
    t = pipeline().results[1]
    assert isinstance(t, HarnessTask), t
    return t


def test_test_edits_are_dropped_and_the_real_fix_still_resolves(task):
    grade = grade_patch(task, task.gold_patch + TEST_EDIT, cache_dir=pipeline().cache)
    assert grade.resolved, grade.error
    assert grade.ignored_files == ["tests/test_calc.py"]
