"""Token budget for the LLM layer (PLAN.md 7): a cap per compendium request.

The service keeps no daily cap (D104, Jan 2026-10-14): the b-api sets the limits per key and switches the LLM off when
one is reached. Until 2.20.0 a daily cap of all workers lived in llm_budget.db in STATE_DIR.

Calls reserve their upper-bound estimate before they start and settle to the actual usage afterwards, so parallel
drafts cannot overshoot a limit between the check and the call; a retry after an attempt that may have reached the
model reserves its prompt again (audit 2026-09-29, L1). The estimate is far above the spend (M13: a batch of
matcher=llm reserved about 13,000 tokens and spent about 8,000), so a call the request budget turns away while other
calls of the request are in flight may wait for them to settle.
"""

from __future__ import annotations

import re
import threading

CHARS_PER_TOKEN = 3  # German prose with citation markers runs at 3 to 5 characters per token; 3 is the safe side
# From U+0800 on - Chinese, Japanese, Korean, but also the typographic quotes and dashes - a character counts as a
# token of its own
_WIDE = re.compile(f"[{chr(0x800)}-{chr(0x10FFFF)}]")


def estimate_tokens(text: str) -> int:
    """Upper-bound estimate used before a call; the API's ``usage`` replaces it afterwards.

    Measured on 2026-09-27 with gpt-6-luna through the b-api, about 2,400 characters each: German 4.62 characters
    per token, Russian 3.96, Arabic 3.27 - three per token is the safe side for all of them -, but Chinese 1.28:
    three per token undercounted it by a factor of 2.35, and a caller's Chinese text could spend a multiple of its
    reservation (audit 2026-09-27, SE-14). Counted as a token each, Chinese comes out 1.28 times its real count.
    """
    _, wide = _WIDE.subn("", text)
    return (len(text) - wide) // CHARS_PER_TOKEN + wide + 1


class TokenBudget:
    """The cap per request in tokens; ``open_request`` opens the budget of one request."""

    def __init__(self, per_request: int) -> None:
        self.per_request = per_request

    def open_request(self, limit: int | None = None, label: str = "der Anfrage") -> RequestBudget:
        """The budget of one request: ``limit`` tokens, else ``per_request`` (the best-quality profiles, D59).
        ``label`` names it in the reason a call falls back for (the check of part 2 has its own, D94)."""
        return RequestBudget(self.per_request if limit is None else limit, label)


class RequestBudget:
    """Budget of one compendium request."""

    def __init__(self, limit: int, label: str = "der Anfrage") -> None:
        self.limit = limit
        self.label = label
        self.used = 0
        self.cached_tokens = 0  # of the used prompt tokens, those the model read from its prompt cache (D69)
        self._reserved = 0
        self._settled = threading.Condition()

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used - self._reserved)

    def count_cached(self, tokens: int) -> None:
        """Count prompt tokens an answer read from the prompt cache; parallel calls of the request add up."""
        with self._settled:
            self.cached_tokens += tokens

    def reserve(self, tokens: int, wait_s: float | None = 0.0) -> str | None:
        """Reserve ``tokens`` for one call; ``None`` when granted, else the reason for the audit.

        While reservations of calls in flight stand in the way and their settling could make room, the call waits up
        to ``wait_s`` seconds for them (``None``: as long as that holds, which the calls' own timeouts bound).
        """
        with self._settled:
            self._settled.wait_for(lambda: self._fits(tokens) or self.used + tokens > self.limit, timeout=wait_s)
            if not self._fits(tokens):
                return f"Token-Budget {self.label} erschöpft ({tokens} Tokens nötig, {self.remaining} frei)"
            self._reserved += tokens
            return None

    def _fits(self, tokens: int) -> bool:
        return self.used + self._reserved + tokens <= self.limit

    def settle(self, reserved: int, actual: int) -> None:
        """Replace a reservation by what the call actually cost (``usage.total_tokens``); waiting calls try again."""
        with self._settled:
            self._reserved = max(0, self._reserved - reserved)
            self.used += actual
            self._settled.notify_all()

    def release(self, reserved: int) -> None:
        """Give a reservation back: the call failed and cost nothing."""
        self.settle(reserved, 0)
