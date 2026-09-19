"""Runtime metrics of the API: requests, compendia, LLM usage, knowledge collections.

The metrics are module-level objects, so every process has one set. With several uvicorn workers,
``PROMETHEUS_MULTIPROC_DIR`` makes prometheus_client keep the values in shared files, and the /metrics
endpoint sums them over all workers (app/api/metrics.py). Everything about a compendium is taken from its
audit after generation, so the service itself knows nothing about Prometheus. Label values come from
fixed sets (route templates, switches, phases), never from user input, to keep the number of series bounded.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

from app.domain.models import Compendium

UNMATCHED_ROUTE = "unmatched"  # 404s: the raw path would let every client create new series
# The method is client input as well: anything else (PROPFIND, invented verbs) shares one label
HTTP_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
OTHER_METHOD = "other"

HTTP_REQUESTS = Counter(
    "kompendium_http_requests_total",
    "HTTP requests by method, route template and status",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "kompendium_http_request_duration_seconds",
    "Duration of HTTP requests by method and route template",
    ["method", "route"],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60, 120),  # REQUEST_TIMEOUT_S defaults to 120
)
COMPENDIA = Counter(
    "kompendium_compendium_requests_total",
    "Generated compendia: was an LLM switch requested, did the LLM contribute (a request may fall back to rules)",
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
LLM_TOKENS = Counter("kompendium_llm_tokens_total", "LLM tokens by type", ["type"])
LLM_CALLS = Counter("kompendium_llm_calls_total", "LLM calls for sections and the router")
LLM_SECTIONS = Counter("kompendium_llm_sections_total", "Blocks the LLM was asked to write, by outcome", ["outcome"])
LLM_SENTENCES = Counter(
    "kompendium_llm_sentences_total",
    "LLM sentences the citation check dropped, found unsupported or marked as conclusions",
    ["outcome"],
)
KNOWLEDGE_MATERIALS = Counter(
    "kompendium_knowledge_materials_total", "Materials of knowledge collections by outcome", ["outcome"]
)
CHUNKS_TRUNCATED = Counter("kompendium_corpus_chunks_truncated_total", "Paragraphs left out by CORPUS_MAX_CHUNKS")


def observe_request(method: str, route: str, status: int, seconds: float) -> None:
    method = method if method in HTTP_METHODS else OTHER_METHOD
    HTTP_REQUESTS.labels(method, route, str(status)).inc()
    HTTP_DURATION.labels(method, route).observe(seconds)


def record_compendium(compendium: Compendium) -> None:
    """Count one generated compendium from its audit: LLM switches, phases, parts, LLM usage, materials."""
    audit = compendium.audit
    requested = str(compendium.frontmatter.get("generation_requested", compendium.generation))
    COMPENDIA.labels(_flag(requested != "rule-based"), _flag(compendium.generation != "rule-based")).inc()
    for phase, milliseconds in audit.timings_ms.items():
        PHASES.labels(phase).observe(milliseconds / 1000)
    for part, section in (("curricula", compendium.curricula), ("collection", compendium.collection)):
        if section is not None:
            PARTS.labels(part, str(section.available).lower()).inc()
    if audit.knowledge is not None:
        _record_knowledge(audit.knowledge)
    if audit.chunks_truncated:
        CHUNKS_TRUNCATED.inc(audit.chunks_truncated)
    if audit.llm_tokens:
        LLM_TOKENS.labels("prompt").inc(audit.llm_tokens.get("prompt", 0))
        LLM_TOKENS.labels("completion").inc(audit.llm_tokens.get("completion", 0))
        LLM_CALLS.inc(audit.llm_tokens.get("calls", 0))
    if audit.llm:
        generation = audit.llm.get("generation") or {}
        LLM_SECTIONS.labels("written").inc(len(generation.get("sections") or []))
        LLM_SECTIONS.labels("fallback").inc(len(generation.get("fallbacks") or {}))
        for outcome in ("dropped", "unsupported", "marked"):
            LLM_SENTENCES.labels(outcome).inc(generation.get(f"{outcome}_sentences", 0))


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _record_knowledge(knowledge: dict[str, object]) -> None:
    readable = "error" not in knowledge
    PARTS.labels("knowledge", str(readable).lower()).inc()
    if not readable:
        return
    for outcome, key in (
        ("used", "sources"),
        ("timed_out", "timed_out"),
        ("empty", "empty"),
        ("skipped_license", "skipped_license"),
    ):
        value = knowledge.get(key)
        if isinstance(value, int):
            KNOWLEDGE_MATERIALS.labels(outcome).inc(value)
    failed = knowledge.get("failed")
    if isinstance(failed, list):
        KNOWLEDGE_MATERIALS.labels("failed").inc(len(failed))
