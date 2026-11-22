"""`wait_until`: wait in a Pilot test for something to become true, not for a fixed time.

    await wait_until(pilot, lambda: screen.record is not None, what="the job to load")

It checks the condition, lets the app run for `POLL_SECONDS`, and checks again, until the
condition holds or `WAIT_SECONDS` pass, which fails the test with what it waited for. A busy
machine only makes it slower, never wrong.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

WAIT_SECONDS = 15.0
POLL_SECONDS = 0.02


async def wait_until(
    pilot: Any, condition: Callable[[], object], *, what: str = "the condition", timeout: float = WAIT_SECONDS
) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(f"waited {timeout:.0f} s for {what}")
        await pilot.pause(POLL_SECONDS)
