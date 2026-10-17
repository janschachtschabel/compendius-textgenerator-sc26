"""Gateway between the orchestrator and the LLM layer (PLAN.md 7): availability, switches, synthesizer, selector.

The service asks the gateway whether the model may be used (start-up check against ``/models``, re-checked
every ``RECHECK_S`` while unavailable), which slots the generation switch writes with the LLM, and for a
per-request budget.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from app.llm.budget import RequestBudget, TokenBudget
from app.llm.client import BApiClient, ModelCheck
from app.llm.credentials import own_key_only, request_key
from app.synthesis.llm import LlmSynthesizer
from app.synthesis.qa import LlmQaWriter
from app.synthesis.selection import LlmSelector

log = logging.getLogger(__name__)

RECHECK_S = 600.0  # an unavailable model is re-checked at most every ten minutes


@dataclass(frozen=True)
class LlmOptions:
    fast_sections: tuple[str, ...] = ("sc26_1", "sc26_11")  # slots generation=llm-fast writes with the LLM
    extraction_candidates: int = 8  # paragraphs offered per block with extraction=llm
    concurrency: int = 10  # kept in step with LLM_MAX_CONCURRENCY; the service always passes the setting
    mark_unsupported: bool = False  # keep failed sentences as conclusion blocks instead of dropping them


class LlmGateway:
    def __init__(
        self,
        client: BApiClient,
        budget: TokenBudget,
        options: LlmOptions | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.budget = budget
        self.options = options or LlmOptions()
        self.synthesizer = LlmSynthesizer(client, mark_unsupported=self.options.mark_unsupported)
        self.selector = LlmSelector(client)
        self.qa = LlmQaWriter(client)
        self.check: ModelCheck | None = None
        self._checked_at = 0.0
        self._clock = clock
        self._lock = threading.Lock()

    def check_model(self) -> ModelCheck:
        """Compare the configured model with ``/models``; the result decides ``available``."""
        check = self.client.check_model()
        with self._lock:
            self.check, self._checked_at = check, self._clock()
        if check.ok:
            log.info("LLM ready: %s", check.message)
        else:
            log.warning("LLM unavailable, LLM requests fall back to the rule-based path: %s", check.message)
        return check

    @property
    def available(self) -> bool:
        if self.client.key_problem() is not None:  # the request brought no key, or the b-api refused it (D105, D106)
            return False
        if self.client.suspended:  # circuit breaker open: answer rule-based now instead of failing slot by slot
            return False
        if not self.client.has_own_key or request_key() is not None:
            # without a key of its own the service checks no model, and with the key of a request a check made with
            # the service's key does not speak for it: the calls of the request tell (D105)
            return True
        check = self.check
        if check is None or (not check.ok and self._clock() - self._checked_at >= RECHECK_S):
            check = self.check_model()
        return check.ok

    @property
    def unavailable_reason(self) -> str:
        return self.client.key_problem() or self._standing_reason()

    def _standing_reason(self) -> str:
        """Why the LLM is not there for this request: the stop that holds it back, else the model check - made with the
        service's key, it speaks for the requests without a key of their own only (review of 2026-10-17)."""
        if self.client.suspended:
            return self.client.suspension_reason
        if self.check is not None and not self.check.ok and request_key() is None:
            return self.check.message  # names the cause (model missing, status, connection error)
        return "Modellprüfung steht aus"

    def last_check(self) -> tuple[bool | None, str | None]:
        """Whether the LLM answered its last check and why not, as /health tells it, never a call to the b-api;
        ``None`` while no check ran. The review page shows it instead of reading a configured LLM as an available one
        (Jan, 2026-10-02: "KI verfügbar" while the b-api answered 502)."""
        if self.client.suspended:
            return False, self.client.suspension_reason
        if self.check is None:
            return None, None
        return (True, None) if self.check.ok else (False, self.check.message)

    def generation_slots(self, generation: str, content_slot_ids: Iterable[str]) -> set[str]:
        """Slot ids the LLM writes under the given generation switch (D10, D33)."""
        ids = set(content_slot_ids)
        if generation == "llm":
            return ids
        if generation == "llm-fast":
            return ids & set(self.options.fast_sections)
        return set()

    def open_budget(self, limit: int | None = None, label: str = "der Anfrage") -> RequestBudget:
        return self.budget.open_request(limit, label)

    def status(self) -> dict[str, Any]:
        """Component status for ``/health``: the last known check, never a call to the b-api. It speaks for the service
        and its own key, also when the request reading it brought a key of its own: that said "Modellprüfung steht aus"
        beside a failed check (review of 2026-10-17)."""
        with own_key_only():
            return self._status()

    def _status(self) -> dict[str, Any]:
        if self.client.has_own_key:
            available = self.check is not None and self.check.ok and not self.client.suspended
        else:  # no model check without a key of its own (D105); a caller's key speaks only for its request
            available = not self.client.suspended
        return {
            "enabled": True,
            "provider": self.client.provider,
            "model": self.client.model,
            "route": self.client.route or None,  # the b-api's routing (D97)
            "available": available,
            # why not: the check names what it found at the start; a stop of the breaker, a key refused or a route
            # gone, said nothing here (review of 2026-10-09, D98)
            "reason": None if available else self._standing_reason(),
            "check": asdict(self.check) if self.check is not None else None,
            "budget": {"per_request": self.budget.per_request},
        }
