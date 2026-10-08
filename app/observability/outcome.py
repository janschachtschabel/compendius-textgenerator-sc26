"""One line per compendium, and per answer of the other endpoints that asked an LLM, with what the request got
(logging review of 2026-10-08).

A best-quality-generated compendium that came back extractive after 300 s left the access line and nothing else: no
sign that the deadline or the budget cut the writing, nor how much. The line names the profile, the parts, the LLM
stages that answered, calls, tokens, the fallbacks by cause and the duration - a digest of the answer's audit, not a
copy. A call skipped for time or budget writes no line of its own; when time or budget cut work, this line is a
WARNING. /qa, /entities, /knowledge and the curriculum search said what their LLM did only in the answer (H2): a
request of theirs that asked an LLM writes the same line, without parts and duration, which the line of the request
gives.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.compendium.llm_report import NOTHING_CONTRIBUTED
from app.domain.models import Compendium

log = logging.getLogger(__name__)

MAX_TOPIC_CHARS = 80
# The cause of a fallback by the words of its reason (app/llm/call.py, app/llm/budget.py, app/llm/client.py,
# app/compendium/llm_policy.py). An LLM that was not there comes first: the breaker's reason names the b-api, which
# was never asked. The time comes before the b-api: a call that waited too long for a free slot fails as
# "b-api: Zeitbudget ..."
CAUSES = (
    ("unavailable", ("LLM nicht verfügbar", "LLM nicht konfiguriert")),
    ("time", ("Zeitbudget",)),
    ("budget", ("Token-Budget", "Tagesbudget", "Budget der Anfrage")),
    ("b-api", ("b-api",)),
)
# What makes the line a WARNING: the request's time or budget cut LLM work, or the LLM it wanted was not there
CUT = ("time", "budget", "unavailable")


def fallback_causes(llm: dict[str, Any] | None) -> dict[str, dict[str, int]]:
    """The fallbacks of the LLM stages in ``llm`` (``audit.llm``) by stage and cause: unavailable, time, budget, b-api,
    other.

    A stage names the reason per block or item (``{"sc26_3": reason}``), the assignment counts the paragraphs per
    reason (``{reason: 88}``), and a stage that was not asked at all names one ``fallback``; the article choice also
    names one for its check of the full-text hits and one for the articles of a topic (D63)."""
    found: dict[str, dict[str, int]] = {}
    for stage, block in _stages(llm):
        counted: Counter[str] = Counter()
        for reason, count in _reasons(block):
            counted[_cause(reason)] += count
        if counted:
            found[stage] = dict(sorted(counted.items()))
    return found


def _stages(llm: dict[str, Any] | None) -> Iterator[tuple[str, dict[str, Any]]]:
    for stage, block in (llm or {}).items():
        if isinstance(block, dict):
            yield stage, block


def _reasons(block: dict[str, Any]) -> Iterator[tuple[str, int]]:
    """Each reason of a stage with the number of blocks, items or paragraphs it holds."""
    for key, value in (block.get("fallbacks") or {}).items():
        yield (str(key), value) if isinstance(value, int) else (str(value), 1)
    for key, value in block.items():
        if (key == "fallback" or key.endswith("_fallback")) and value:
            yield str(value), 1


def _cause(reason: str) -> str:
    for name, words in CAUSES:
        if any(word in reason for word in words):
            return name
    return "other"


@dataclass(frozen=True)
class _Digest:
    """What the LLM did for one answer, from its ``audit.llm`` and ``audit.llm_tokens``."""

    stages: list[str]  # the stages the LLM answered
    causes: dict[str, dict[str, int]]
    unavailable: str | None  # why the LLM the request wanted was not there
    calls: int
    tokens: int

    @property
    def level(self) -> int:
        cut = any(cause in counted for counted in self.causes.values() for cause in CUT)
        return logging.WARNING if cut or self.unavailable else logging.INFO

    @property
    def fallbacks(self) -> str:
        return (
            ", ".join(
                f"{stage} " + " ".join(f"{cause}={count}" for cause, count in counted.items())
                for stage, counted in self.causes.items()
            )
            or "none"
        )

    @property
    def suffix(self) -> str:
        return f"; {self.unavailable}" if self.unavailable else ""


def _digest(llm: dict[str, Any] | None, tokens: dict[str, int] | None) -> _Digest:
    causes = fallback_causes(llm)
    return _Digest(
        stages=[stage for stage, block in _stages(llm) if block.get("used") == "llm"],
        causes=causes,
        unavailable=_unavailable(llm),
        calls=(tokens or {}).get("calls", 0),
        tokens=(tokens or {}).get("total", 0),
    )


def _unavailable(llm: dict[str, Any] | None) -> str | None:
    """The note of an LLM that was not there; where only a stage says so - a check the curriculum search asked without
    an article to choose -, that stage's reason."""
    note = (llm or {}).get("note")
    if note and note != NOTHING_CONTRIBUTED:
        return str(note)
    reasons = (reason for _, block in _stages(llm) for reason, _ in _reasons(block))
    return next((reason for reason in reasons if _cause(reason) == "unavailable"), None)


def log_compendium(compendium: Compendium) -> None:
    """The line of one generated compendium; a WARNING when time or budget cut LLM work, or when the request wanted an
    LLM that was not there - the breaker open, none configured -, with the reason the audit gives."""
    audit = compendium.audit
    digest = _digest(audit.llm, audit.llm_tokens)
    fields: dict[str, Any] = {
        "answer": "compendium",
        "topic": compendium.topic[:MAX_TOPIC_CHARS],
        "preset": audit.preset or "-",
        "parts": dict(audit.parts_status),
        "llm": digest.stages,
        "llm_calls": digest.calls,
        "llm_tokens": digest.tokens,
        "fallbacks": digest.causes,
        "duration_ms": audit.duration_ms,
        "llm_unavailable": digest.unavailable,
    }
    log.log(
        digest.level,
        "compendium %r: %s, parts %s, LLM %s, %d calls, %d tokens, fallbacks %s, %s ms%s",
        fields["topic"],
        fields["preset"],
        "/".join(f"{part} {status}" for part, status in fields["parts"].items()) or "-",
        ",".join(digest.stages) or "none",
        digest.calls,
        digest.tokens,
        digest.fallbacks,
        audit.duration_ms if audit.duration_ms is not None else "-",
        digest.suffix,
        extra={"fields": fields},
    )


def log_answer(
    what: str, topic: str | None, preset: str, llm: dict[str, Any] | None, tokens: dict[str, int] | None
) -> None:
    """The line of one answer of /qa, /entities, /knowledge or the curriculum search (``what``) that asked an LLM, by
    the rule of the compendium's line. ``llm`` holds the stages as ``audit.llm`` does - ``used``, the fallbacks, the
    note of an LLM that was not there -, ``tokens`` the calls and the total as ``audit.llm_tokens``. ``topic`` names
    the line where the request has one."""
    digest = _digest(llm, tokens)
    fields: dict[str, Any] = {
        "answer": what,
        "topic": topic[:MAX_TOPIC_CHARS] if topic else None,
        "preset": preset,
        "llm": digest.stages,
        "llm_calls": digest.calls,
        "llm_tokens": digest.tokens,
        "fallbacks": digest.causes,
        "llm_unavailable": digest.unavailable,
    }
    log.log(
        digest.level,
        "%s%s: %s, LLM %s, %d calls, %d tokens, fallbacks %s%s",
        what,
        f" {fields['topic']!r}" if fields["topic"] else "",
        preset,
        ",".join(digest.stages) or "none",
        digest.calls,
        digest.tokens,
        digest.fallbacks,
        digest.suffix,
        extra={"fields": fields},
    )
