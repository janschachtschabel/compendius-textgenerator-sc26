"""Audit block, token counts and frontmatter block of the LLM layer for one compendium (PLAN.md 7, D33)."""

from __future__ import annotations

from typing import Any

from app.llm.gateway import LlmGateway
from app.synthesis.extraction import ExtractionReport
from app.synthesis.writer import LlmReport

NOTHING_CONTRIBUTED = "LLM hat keinen Baustein ausgewählt oder geschrieben; Regelmodus verwendet"
MODEL_KNOWLEDGE_NOTE = (
    "Sätze mit Evidenzgrad=Modellwissen stammen aus dem Wissen des Sprachmodells, nicht aus den "
    "aufgeführten Quellen, und sind nicht belegt."
)


def build_llm_report(
    gateway: LlmGateway | None,
    *,
    extraction_requested: str,
    extraction_used: str,
    generation_requested: str,
    generation_used: str,
    enrichment_requested: str,
    enrichment_used: str,
    note: str | None,
    extraction: ExtractionReport | None,
    generation: LlmReport | None,
) -> tuple[dict[str, Any] | None, dict[str, int] | None, dict[str, Any] | None]:
    """Audit block, token counts and frontmatter block of the LLM layer; all ``None`` when no switch asked for it."""
    if extraction_requested == "rule-based" and generation_requested == "rule-based":
        return None, None, None
    reports: list[ExtractionReport | LlmReport] = [r for r in (extraction, generation) if r is not None]
    calls = sum(r.calls for r in reports)
    tokens: dict[str, int] | None = None
    if calls:
        tokens = {
            "prompt": sum(r.prompt_tokens for r in reports),
            "completion": sum(r.completion_tokens for r in reports),
            "total": sum(r.total_tokens for r in reports),
            "calls": calls,
        }
    if note is None and extraction_used == "rule-based" and generation_used == "rule-based":
        note = NOTHING_CONTRIBUTED
    extraction_block: dict[str, Any] = {
        "requested": extraction_requested,
        "used": extraction_used,
        "sections": list(extraction.slots) if extraction else [],
        "emptied": list(extraction.emptied) if extraction else [],
        "fallbacks": dict(extraction.fallbacks) if extraction else {},
        "offered": extraction.offered if extraction else 0,
        "sentences": extraction.sentences if extraction else 0,
        "invalid_numbers": extraction.invalid if extraction else 0,
        "deduped_sentences": extraction.deduped if extraction else 0,
        "cut_sentences": extraction.cut if extraction else 0,
    }
    generation_block: dict[str, Any] = {
        "requested": generation_requested,
        "used": generation_used,
        "sections": list(generation.sections) if generation else [],
        "fallbacks": dict(generation.fallbacks) if generation else {},
        "dropped_sentences": generation.dropped_sentences if generation else 0,
        "unsupported_sentences": generation.unsupported_sentences if generation else 0,
        "marked_sentences": generation.marked_sentences if generation else 0,
        "enrichment": enrichment_used,
        "enrichment_requested": enrichment_requested,
    }
    audit: dict[str, Any] = {"note": note, "extraction": extraction_block, "generation": generation_block}
    front: dict[str, Any] = {}
    if gateway is not None:
        models = [r.model for r in (generation, extraction) if r is not None and r.model]
        front["provider"] = gateway.client.provider
        front["model"] = models[0] if models else gateway.client.model
    front["prompts"] = sorted({prompt for r in reports for prompt in r.prompts})
    front["extraction"] = {
        "sections": extraction_block["sections"],
        "emptied": extraction_block["emptied"],
        "fallbacks": extraction_block["fallbacks"],
    }
    front["generation"] = {"sections": generation_block["sections"], "fallbacks": generation_block["fallbacks"]}
    if enrichment_used == "model-knowledge":
        # The reader has to be able to see this without reading the audit block (docs/umbau.md U4)
        front["enrichment"] = {
            "mode": enrichment_used,
            "marked_sentences": generation_block["marked_sentences"],
            "hinweis": MODEL_KNOWLEDGE_NOTE,
        }
    if note:
        front["note"] = note
    return audit, tokens, front
