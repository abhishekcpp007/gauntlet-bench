from dataclasses import replace

from gauntlet.tui.cells import run_detail, run_oracle, run_violations
from gauntlet.tui.theme import make_look

from .factories import make_source

LOOK = make_look({})


def test_run_cells():
    golden, shipped = make_source().runs()
    assert run_oracle(golden, LOOK).plain == "✓ 3/3"
    assert run_oracle(replace(golden, oracle=None), LOOK).plain == "-"
    assert run_violations(golden, LOOK).plain == "✓ none"
    assert run_violations(replace(golden, violations=2), LOOK).plain == "▲ 2"
    assert run_violations(replace(golden, violations=None), LOOK).plain == "not checked"
    assert run_detail(golden, LOOK).plain == "full"
    assert run_detail(shipped, LOOK).plain == "◌ summary"
