"""Runtime metrics of the API: requests, compendia, LLM usage, knowledge collections.

The metrics are module-level objects, so every process has one set. With several uvicorn workers,
``PROMETHEUS_MULTIPROC_DIR`` makes prometheus_client keep the values in shared files, and the /metrics
endpoint sums them over all workers (app/api/metrics.py). Everything about a compendium is taken from its
audit after generation, so the service itself knows nothing about Prometheus. Label values come from
fixed sets (route templates, switches, phases), never from user input, to keep the number of series bounded.
"""

from __future__ import annotations

from contextvars import ContextVar

from prometheus_client import Counter, Histogram

from app.domain.models import Compendium
from app.matching.registry import LLM_MATCHER

UNMATCHED_ROUTE = "unmatched"  # 404s: the raw path would let every client create new series
# The method is client input as well: anything else (PROPFIND, invented verbs) shares one label
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
OTHER_METHOD = "other"

HTTP_REQUESTS = Counter(
    "kompendium_http_requests_total",
    "HTTP requests by method, route template and status",
    ["method", "route", "status"],
)
# Up to the longest a request may take: REQUEST_TIMEOUT_S, 300 s with openai, 600 s with academiccloud (D93)
DURATION_BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120, 300, 600)
HTTP_DURATION = Histogram(
    "kompendium_http_request_duration_seconds",
    "Duration of HTTP requests by method and route template",
    ["method", "route"],
    buckets=DURATION_BUCKETS,
)
COMPENDIA = Counter(
    "kompendium_compendium_requests_total",
    "Generated compendia: was an LLM switch, matcher=llm or article_choice=llm requested, did the LLM contribute "
    "(a request may fall back to rules)",
    ["llm_requested", "llm_used"],
)
PHASES = Histogram(
    "kompendium_compendium_phase_seconds",
    "Duration of the generation phases (audit.timings_ms)",
    ["phase"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
PARTS = Counter(
    "kompendium_parts_total",
    "Curricula, collection and knowledge collection per compendium, by availability",
    ["part", "available"],
)
# Every LLM call of every endpoint, counted where all of them pass (app.llm.call.budgeted_chat): only POST
# /compendium counted before, from its audit (audit 2026-09-27, BE-04)
LLM_TOKENS = Counter("kompendium_llm_tokens_total", "LLM tokens by route and type", ["endpoint", "type"])
LLM_CALLS = Counter(
    "kompendium_llm_calls_total",
    "LLM calls by route and outcome: answered, failed (no usable answer), skipped (no budget or time left)",
    ["endpoint", "outcome"],
)
_llm_endpoint: ContextVar[str] = ContextVar("llm_endpoint", default="none")  # "none": no request, the CLI
LLM_SECTIONS = Counter("kompendium_llm_sections_total", "Blocks the LLM was asked to write, by outcome", ["outcome"])
LLM_SELECTIONS = Counter(
    "kompendium_llm_selections_total",
    "Blocks whose sentences the LLM was asked to choose (extraction=llm), by outcome: chosen, emptied, fallback",
    ["outcome"],
)
LLM_SENTENCES = Counter(
    "kompendium_llm_sentences_total",
    "LLM sentences the citation check dropped, found unsupported or marked as conclusions",
    ["outcome"],
)
KNOWLEDGE_MATERIALS = Counter(
    "kompendium_knowledge_materials_total", "Materials of knowledge collections by outcome", ["outcome"]
)
CHUNKS_TRUNCATED = Counter("kompendium_corpus_chunks_truncated_total", "Paragraphs left out by CORPUS_MAX_CHUNKS")


def set_llm_endpoint(route: str) -> None:
    """The route of the request being handled, as the label of the LLM calls it makes."""
    _llm_endpoint.set(route)


def record_llm_call(outcome: str, prompt_tokens: int = 0, completion_tokens: int = 0, cached_tokens: int = 0) -> None:
    endpoint = _llm_endpoint.get()
    LLM_CALLS.labels(endpoint, outcome).inc()
    if prompt_tokens:
        LLM_TOKENS.labels(endpoint, "prompt").inc(prompt_tokens)
    if completion_tokens:
        LLM_TOKENS.labels(endpoint, "completion").inc(completion_tokens)
    if cached_tokens:  # part of the prompt tokens, read from the prompt cache (D69)
        LLM_TOKENS.labels(endpoint, "cached").inc(cached_tokens)


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    method = method if method in HTTP_METHODS else OTHER_METHOD
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(seconds)


def record_compendium(compendium: Compendium) -> None:
    """Count one generated compendium from its audit: LLM switches, phases, parts, LLM usage, materials."""
    audit = compendium.audit
    front = compendium.frontmatter
    # article_choice=llm (D35) counts like a switch where the model had something to answer - an unsure article, side
    # articles, a material, since D63 the articles of every topic; a request with nothing to ask counted as a
    # fallback would set off the LLM alarms
    choice = (audit.llm or {}).get("article_choice") or {}
    requested = (
        front.get("extraction_requested", compendium.extraction),
        front.get("generation_requested", compendium.generation),
        _matching(front.get("matcher_requested", audit.matcher)),
        choice.get("requested", "rule-based") if choice.get("needed") else "rule-based",
    )
    used = (compendium.extraction, compendium.generation, _matching(audit.matcher), choice.get("used", "rule-based"))
    COMPENDIA.labels(_flag(requested), _flag(used)).inc()
    for phase, milliseconds in audit.timings_ms.items():
        PHASES.labels(phase).observe(milliseconds / 1000)
    for part, section in (("curricula", compendium.curricula), ("collection", compendium.collection)):
        if section is not None:
            PARTS.labels(part, str(section.available).lower()).inc()
    if audit.knowledge is not None:
        _record_knowledge(audit.knowledge)
    if audit.chunks_truncated:
        CHUNKS_TRUNCATED.inc(audit.chunks_truncated)
    if audit.llm:
        extraction = audit.llm.get("extraction") or {}
        emptied = len(extraction.get("emptied") or [])
        LLM_SELECTIONS.labels("chosen").inc(len(extraction.get("sections") or []) - emptied)
        LLM_SELECTIONS.labels("emptied").inc(emptied)
        LLM_SELECTIONS.labels("fallback").inc(len(extraction.get("fallbacks") or {}))
        generation = audit.llm.get("generation") or {}
        LLM_SECTIONS.labels("written").inc(len(generation.get("sections") or []))
        LLM_SECTIONS.labels("fallback").inc(len(generation.get("fallbacks") or {}))
        for outcome in ("dropped", "unsupported", "marked"):
            LLM_SENTENCES.labels(outcome).inc(generation.get(f"{outcome}_sentences", 0))


def _flag(switches: tuple[object, ...]) -> str:
    """``"true"`` when any of the switches asks for (or used) the LLM."""
    return "true" if any(switch != "rule-based" for switch in switches) else "false"


def _matching(matcher: object) -> str:
    """matcher=llm as a switch value: ``llm``, every local strategy ``rule-based`` (D34)."""
    return "llm" if matcher == LLM_MATCHER else "rule-based"


def _record_knowledge(knowledge: dict[str, object]) -> None:
    readable = "error" not in knowledge
    PARTS.labels("knowledge", str(readable).lower()).inc()
    if not readable:
        return
    for outcome, key in (
        ("used", "sources"),
        ("timed_out", "timed_out"),
        ("empty", "empty"),
    ):
        value = knowledge.get(key)
        if isinstance(value, int):
            KNOWLEDGE_MATERIALS.labels(outcome).inc(value)
    failed = knowledge.get("failed")
    if isinstance(failed, list):
        KNOWLEDGE_MATERIALS.labels("failed").inc(len(failed))
