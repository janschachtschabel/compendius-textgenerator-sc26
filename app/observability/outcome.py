"""One line per compendium with what the request got (logging review of 2026-10-08).

A best-quality-generated compendium that came back extractive after 300 s left the access line and nothing else: no
sign that the deadline or the budget cut the writing, nor how much. The line names the profile, the parts, the LLM
stages that answered, calls, tokens, the fallbacks by cause and the duration - a digest of the answer's audit, not a
copy. A call skipped for time or budget writes no line of its own; when time or budget cut work, this line is a
WARNING.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from app.compendium.llm_report import NOTHING_CONTRIBUTED
from app.domain.models import Compendium

log = logging.getLogger(__name__)

MAX_TOPIC_CHARS = 80
# The cause of a fallback by the words of its reason (app/llm/call.py, app/llm/budget.py, app/llm/client.py); the time
# comes first: a call that waited too long for a free slot fails as "b-api: Zeitbudget ..."
CAUSES = (
    ("time", ("Zeitbudget",)),
    ("budget", ("Token-Budget", "Tagesbudget", "Budget der Anfrage")),
    ("b-api", ("b-api",)),
)
CUT = ("time", "budget")


def fallback_causes(llm: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """The fallbacks of the LLM stages in ``llm`` (``audit.llm``) by stage and cause: time, budget, b-api, other.

    A stage names the reason per block or item (``{"sc26_3": reason}``), the assignment counts the paragraphs per
    reason (``{reason: 88}``), and a stage that was not asked at all names one ``fallback``."""
    found: dict[str, dict[str, int]] = {}
    for stage, block in (llm or {}).items():
        if not isinstance(block, dict):
            continue
        counted: Counter[str] = Counter()
        for key, value in (block.get("fallbacks") or {}).items():
            if isinstance(value, int):
                counted[_cause(str(key))] += value
            else:
                counted[_cause(str(value))] += 1
        if block.get("fallback"):
            counted[_cause(str(block["fallback"]))] += 1
        if counted:
            found[stage] = dict(sorted(counted.items()))
    return found


def _cause(reason: str) -> str:
    for name, words in CAUSES:
        if any(word in reason for word in words):
            return name
    return "other"


def log_compendium(compendium: Compendium) -> None:
    """The line of one generated compendium; a WARNING when time or budget cut LLM work, or when the request wanted an
    LLM that was not there - the breaker open, none configured -, with the reason the audit's note gives."""
    audit = compendium.audit
    causes = fallback_causes(audit.llm)
    note = (audit.llm or {}).get("note")
    unavailable = str(note) if note and note != NOTHING_CONTRIBUTED else None
    stages = [
        name for name, block in (audit.llm or {}).items() if isinstance(block, dict) and block.get("used") == "llm"
    ]
    tokens = audit.llm_tokens or {}
    fields: dict[str, Any] = {
        "topic": compendium.topic[:MAX_TOPIC_CHARS],
        "preset": audit.preset or "-",
        "parts": dict(audit.parts_status),
        "llm": stages,
        "llm_calls": tokens.get("calls", 0),
        "llm_tokens": tokens.get("total", 0),
        "fallbacks": causes,
        "duration_ms": audit.duration_ms,
        "llm_unavailable": unavailable,
    }
    cut = any(cause in stage for stage in causes.values() for cause in CUT)
    log.log(
        logging.WARNING if cut or unavailable else logging.INFO,
        "compendium %r: %s, parts %s, LLM %s, %d calls, %d tokens, fallbacks %s, %s ms%s",
        fields["topic"],
        fields["preset"],
        "/".join(f"{part} {status}" for part, status in fields["parts"].items()) or "-",
        ",".join(stages) or "none",
        fields["llm_calls"],
        fields["llm_tokens"],
        ", ".join(
            f"{stage} " + " ".join(f"{cause}={count}" for cause, count in counted.items())
            for stage, counted in causes.items()
        )
        or "none",
        audit.duration_ms if audit.duration_ms is not None else "-",
        f"; {unavailable}" if unavailable else "",
        extra={"fields": fields},
    )
