"""Time budget of one compendium request for its LLM work (``REQUEST_TIMEOUT_S``, PLAN.md 8.3).

Every LLM call gets the smaller of its configured timeout and the time that is left; when too little is left to
start a call, the block is written extractively instead. The rule-based path is fast and needs no deadline.
"""

from __future__ import annotations

import time
from collections.abc import Callable

MIN_CALL_S = 5.0  # with less time left a call is not worth starting


class Deadline:
    def __init__(self, seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._end = clock() + seconds

    def remaining(self) -> float:
        return max(0.0, self._end - self._clock())

    def call_timeout(self, configured_s: float) -> float | None:
        """Timeout for a call that starts now, or ``None`` when the request has no time left for one."""
        remaining = self.remaining()
        if remaining < MIN_CALL_S:
            return None
        return min(configured_s, remaining)

    def wait_s(self) -> float:
        """How long a call may wait to start (for room in the token budget) and still get ``MIN_CALL_S`` to run."""
        return max(0.0, self.remaining() - MIN_CALL_S)
