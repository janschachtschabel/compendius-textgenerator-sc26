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
from app.llm.client import SUSPENDED_MESSAGE, BApiClient, ModelCheck
from app.synthesis.llm import LlmSynthesizer
from app.synthesis.qa import LlmQaWriter
from app.synthesis.selection import LlmSelector

log = logging.getLogger(__name__)

RECHECK_S = 600.0  # an unavailable model is re-checked at most every ten minutes


@dataclass(frozen=True)
class LlmOptions:
    fast_sections: tuple[str, ...] = ("sc26_1", "sc26_11")  # slots generation=llm-fast writes with the LLM
    extraction_candidates: int = 8  # paragraphs offered per block with extraction=llm
    concurrency: int = 4
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
        if self.client.suspended:  # circuit breaker open: answer rule-based now instead of failing slot by slot
            return False
        check = self.check
        if check is None or (not check.ok and self._clock() - self._checked_at >= RECHECK_S):
            check = self.check_model()
        return check.ok

    @property
    def unavailable_reason(self) -> str:
        if self.check is not None and not self.check.ok:
            return self.check.message  # names the cause (model missing, status, connection error)
        if self.client.suspended:
            return SUSPENDED_MESSAGE
        return "Modellprüfung steht aus"

    def generation_slots(self, generation: str, content_slot_ids: Iterable[str]) -> set[str]:
        """Slot ids the LLM writes under the given generation switch (D10, D33)."""
        ids = set(content_slot_ids)
        if generation == "llm":
            return ids
        if generation == "llm-fast":
            return ids & set(self.options.fast_sections)
        return set()

    def open_budget(self) -> RequestBudget:
        return self.budget.open_request()

    def status(self) -> dict[str, Any]:
        """Component status for ``/health``: the last known check, never a call to the b-api."""
        return {
            "enabled": True,
            "provider": self.client.provider,
            "model": self.client.model,
            "available": self.check is not None and self.check.ok and not self.client.suspended,
            "check": asdict(self.check) if self.check is not None else None,
            "budget": {
                "per_request": self.budget.per_request,
                "daily": self.budget.daily,
                "used_today": self.budget.used_today,
            },
        }
