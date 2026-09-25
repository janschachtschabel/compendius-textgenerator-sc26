"""Audit block, token counts and frontmatter block of the LLM layer for one compendium (PLAN.md 7, D33)."""

from __future__ import annotations

from typing import Any

from app.knowledge.article_choice import ArticleChoiceReport, HitCheckReport, choice_block
from app.knowledge.node_article import NodeArticleReport
from app.llm.gateway import LlmGateway
from app.matching.llm_assignment import LlmAssignmentReport
from app.synthesis.extraction import ExtractionReport
from app.synthesis.writer import LlmReport

NOTHING_CONTRIBUTED = (
    "LLM hat keinen Artikel gewählt, keinen Absatz zugeordnet und keinen Baustein ausgewählt oder geschrieben; "
    "Regelmodus verwendet"
)
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
    matching_requested: str = "rule-based",
    matching_used: str = "rule-based",
    matching: LlmAssignmentReport | None = None,
    choice_requested: str = "rule-based",
    choice_used: str = "rule-based",
    choice: ArticleChoiceReport | None = None,
    choice_chosen: str | None = None,
    choice_needed: bool = False,
    hit_check: HitCheckReport | None = None,
    node: NodeArticleReport | None = None,
) -> tuple[dict[str, Any] | None, dict[str, int] | None, dict[str, Any] | None]:
    """Audit block, token counts and frontmatter block of the LLM layer; all ``None`` when nothing asked for it.

    ``matching_*`` describe matcher=llm (D34), ``choice_*`` article_choice=llm (D35): ``llm`` or ``rule-based``,
    like the two switches; ``choice_chosen`` is the article the model decided on, ``hit_check`` what it did with the
    side articles, and ``choice_needed`` whether there was anything to ask - an unsure article, side articles or a
    material; only then is the model asked, so only then is its absence a fallback. ``node`` is the question about a
    material (D47): its tokens and prompt count here, its answer and why it did not decide are in audit.node_article.
    """
    if extraction_requested == generation_requested == matching_requested == choice_requested == "rule-based":
        return None, None, None
    reports: list[
        ExtractionReport | LlmReport | LlmAssignmentReport | ArticleChoiceReport | HitCheckReport | NodeArticleReport
    ] = [r for r in (node, choice, hit_check, matching, extraction, generation) if r is not None]
    calls = sum(r.calls for r in reports)
    tokens: dict[str, int] | None = None
    if calls:
        tokens = {
            "prompt": sum(r.prompt_tokens for r in reports),
            "completion": sum(r.completion_tokens for r in reports),
            "total": sum(r.total_tokens for r in reports),
            "calls": calls,
        }
    if note is None and extraction_used == generation_used == matching_used == choice_used == "rule-based":
        note = NOTHING_CONTRIBUTED
    article_choice = choice_block(choice_requested, choice_used, choice_needed, choice, choice_chosen, hit_check)
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
    matching_block: dict[str, Any] = {
        "requested": matching_requested,
        "used": matching_used,
        "paragraphs": matching.paragraphs if matching else 0,
        "answered": matching.answered if matching else 0,
        "fallback_paragraphs": matching.fallback if matching else 0,
        "fallbacks": dict(matching.fallbacks) if matching else {},
        "unknown_keys": matching.unknown_keys if matching else 0,
    }
    audit: dict[str, Any] = {
        "note": note,
        "article_choice": article_choice,
        "matching": matching_block,
        "extraction": extraction_block,
        "generation": generation_block,
    }
    front: dict[str, Any] = {}
    if gateway is not None:
        models = [
            r.model for r in (generation, extraction, matching, choice, hit_check, node) if r is not None and r.model
        ]
        front["provider"] = gateway.client.provider
        front["model"] = models[0] if models else gateway.client.model
    front["prompts"] = sorted({prompt for r in reports for prompt in r.prompts})
    front["extraction"] = {
        "sections": extraction_block["sections"],
        "emptied": extraction_block["emptied"],
        "fallbacks": extraction_block["fallbacks"],
    }
    front["generation"] = {"sections": generation_block["sections"], "fallbacks": generation_block["fallbacks"]}
    if matching_requested == "llm":
        front["matching"] = {
            key: matching_block[key] for key in ("paragraphs", "answered", "fallback_paragraphs", "fallbacks")
        }
    if article_choice["asked"] or article_choice["hits_checked"]:
        keys = ("offered", "chosen", "fallback", "hits_checked", "hits_dropped", "hits_fallback")
        front["article_choice"] = {key: article_choice[key] for key in keys}
    if enrichment_used == "model-knowledge":
        # The reader has to be able to see this without reading the audit block (docs/umbau.md U4). The note
        # explains marked sentences, so it only appears where there are any - the model may stay in the sources.
        marked = generation_block["marked_sentences"]
        front["enrichment"] = {"mode": enrichment_used, "marked_sentences": marked}
        if marked:
            front["enrichment"]["hinweis"] = MODEL_KNOWLEDGE_NOTE
    if note:
        front["note"] = note
    return audit, tokens, front
