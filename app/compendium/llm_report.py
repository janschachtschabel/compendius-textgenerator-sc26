"""Audit block, token counts and frontmatter block of the LLM layer for one compendium (PLAN.md 7, D33)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.compendium.gateway import LlmGateway
from app.knowledge.article_choice import ArticleChoiceReport, ChoiceAudit, HitCheckReport, choice_block
from app.knowledge.curriculum_check import CurriculumCheckReport
from app.knowledge.node_article import NodeArticleReport
from app.knowledge.topic_articles import TopicArticlesReport
from app.knowledge.topic_wording import TopicWordingReport
from app.matching.llm_assignment import LlmAssignmentReport
from app.synthesis.citations import MODEL_KNOWLEDGE_LABEL
from app.synthesis.extraction import ExtractionReport
from app.synthesis.model_knowledge_check import ModelKnowledgeCheckReport
from app.synthesis.writer import LlmReport

NOTHING_CONTRIBUTED = (
    "LLM hat keinen Artikel gewählt, keinen Absatz zugeordnet und keinen Baustein ausgewählt oder geschrieben; "
    "Regelmodus verwendet"
)
MODEL_KNOWLEDGE_NOTE = (
    f"Sätze mit dem Zusatz {MODEL_KNOWLEDGE_LABEL} (im Markup Evidenzgrad=Modellwissen) stammen aus dem Wissen des "
    "Sprachmodells, nicht aus den aufgeführten Quellen, und sind nicht belegt."
)


@dataclass(frozen=True)
class LlmWork:
    """What the LLM layer of one request was asked for and did: each switch as requested and as used (``llm`` or
    ``rule-based``; enrichment ``sources-only``, ``model-knowledge`` or ``model-knowledge-full``), and the report of
    each stage that ran.
    build_llm_report took these as 24 parameters, the article choice spread in from a dict (audit 2026-09-28, WA-06).

    ``matching_*`` describe matcher=llm (D34) and ``choice`` the article choice (D35, D47, D63): the model is asked
    only when ``choice.needed``, so only then is its absence a fallback; the question about a material (``choice.node``)
    counts its tokens and prompt here, its answer and why it did not decide are in audit.node_article.
    ``curriculum_*`` describe curriculum_check=llm (D58): what the model rated in part 2, and why the rules decided
    when it was not asked. ``wording``: a writing profile let the model word the topic of a text (D72).
    """

    note: str | None = None
    extraction_requested: str = "rule-based"
    extraction_used: str = "rule-based"
    extraction: ExtractionReport | None = None
    generation_requested: str = "rule-based"
    generation_used: str = "rule-based"
    generation: LlmReport | None = None
    enrichment_requested: str = "sources-only"
    enrichment_used: str = "sources-only"
    matching_requested: str = "rule-based"
    matching_used: str = "rule-based"
    matching: LlmAssignmentReport | None = None
    choice: ChoiceAudit = field(default_factory=ChoiceAudit)
    curriculum_requested: str = "rule-based"
    curriculum: CurriculumCheckReport | None = None
    curriculum_fallback: str | None = None
    cached_tokens: int = 0  # of the prompt tokens, those read from the prompt cache (D69)
    wording: TopicWordingReport | None = None
    check_requested: str = "rule-based"  # model_knowledge_check (07, point 12a)
    check: ModelKnowledgeCheckReport | None = None


def build_llm_report(
    gateway: LlmGateway | None, work: LlmWork
) -> tuple[dict[str, Any] | None, dict[str, int] | None, dict[str, Any] | None]:
    """Audit block, token counts and frontmatter block of the LLM layer; all ``None`` when nothing asked for it."""
    choice_audit = work.choice
    extraction, generation, matching, curriculum = work.extraction, work.generation, work.matching, work.curriculum
    wording, check = work.wording, work.check
    choice, hit_check, node, articles = (
        choice_audit.report,
        choice_audit.hit_check,
        choice_audit.node,
        choice_audit.articles,
    )
    requested = (
        work.extraction_requested,
        work.generation_requested,
        work.matching_requested,
        choice_audit.requested,
        work.curriculum_requested,
        work.check_requested,
    )
    if all(switch == "rule-based" for switch in requested):
        return None, None, None
    reports: list[
        ExtractionReport
        | LlmReport
        | LlmAssignmentReport
        | ArticleChoiceReport
        | HitCheckReport
        | NodeArticleReport
        | TopicArticlesReport
        | TopicWordingReport
        | CurriculumCheckReport
        | ModelKnowledgeCheckReport
    ] = [
        r
        for r in (wording, node, articles, choice, hit_check, matching, extraction, generation, check, curriculum)
        if r is not None
    ]
    curriculum_used = "llm" if curriculum is not None and curriculum.answered else "rule-based"
    calls = sum(r.calls for r in reports)
    tokens: dict[str, int] | None = None
    if calls:
        tokens = {
            "prompt": sum(r.prompt_tokens for r in reports),
            "completion": sum(r.completion_tokens for r in reports),
            "total": sum(r.total_tokens for r in reports),
            "calls": calls,
            "cached": work.cached_tokens,
        }
    used = (work.extraction_used, work.generation_used, work.matching_used, choice_audit.used, curriculum_used)
    note = work.note
    if note is None and all(switch == "rule-based" for switch in used):
        note = NOTHING_CONTRIBUTED
    article_choice = choice_block(choice_audit)
    extraction_block: dict[str, Any] = {
        "requested": work.extraction_requested,
        "used": work.extraction_used,
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
        "requested": work.generation_requested,
        "used": work.generation_used,
        "sections": list(generation.sections) if generation else [],
        "fallbacks": dict(generation.fallbacks) if generation else {},
        "dropped_sentences": generation.dropped_sentences if generation else 0,
        "unsupported_sentences": generation.unsupported_sentences if generation else 0,
        "marked_sentences": generation.marked_sentences if generation else 0,
        "enrichment": work.enrichment_used,
        "enrichment_requested": work.enrichment_requested,
    }
    matching_block: dict[str, Any] = {
        "requested": work.matching_requested,
        "used": work.matching_used,
        "paragraphs": matching.paragraphs if matching else 0,
        "answered": matching.answered if matching else 0,
        "fallback_paragraphs": matching.fallback if matching else 0,
        "fallbacks": dict(matching.fallbacks) if matching else {},
        "unknown_keys": matching.unknown_keys if matching else 0,
        "asked_again": matching.asked_again if matching else 0,  # batches asked once more (V4)
    }
    curriculum_block: dict[str, Any] = {
        "requested": work.curriculum_requested,
        "used": curriculum_used,
        "rated": curriculum.rated if curriculum else 0,
        "answered": curriculum.answered if curriculum else 0,
        "dropped": curriculum.dropped if curriculum else 0,
        "fallbacks": dict(curriculum.fallbacks) if curriculum else {},
        "fallback": work.curriculum_fallback,  # why the model was not asked at all
    }
    audit: dict[str, Any] = {
        "note": note,
        "article_choice": article_choice,
        "matching": matching_block,
        "extraction": extraction_block,
        "generation": generation_block,
        "curriculum_check": curriculum_block,
        "model_knowledge_check": {
            "requested": work.check_requested,
            "used": "llm" if check is not None and check.sections else "rule-based",
            "sections": list(check.sections) if check else [],
            "checked": check.checked if check else 0,
            "struck": check.struck if check else 0,
            "corrected": check.corrected if check else 0,
            "fallbacks": dict(check.fallbacks) if check else {},
        },
        "topic_wording": (
            {"source": wording.source, "reason": wording.reason, "topic": wording.topic, "fallback": wording.fallback}
            if wording is not None
            else None
        ),
    }
    front: dict[str, Any] = {}
    if gateway is not None:
        models = [
            r.model
            for r in (generation, extraction, matching, choice, hit_check, node, articles, curriculum, wording, check)
            if r is not None and r.model
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
    if work.matching_requested == "llm":
        front["matching"] = {
            key: matching_block[key] for key in ("paragraphs", "answered", "fallback_paragraphs", "fallbacks")
        }
    if work.curriculum_requested == "llm":
        front["curriculum_check"] = {key: curriculum_block[key] for key in ("rated", "dropped", "fallback")}
    if work.check_requested == "llm":
        checked = audit["model_knowledge_check"]
        front["model_knowledge_check"] = {key: checked[key] for key in ("checked", "struck", "corrected")}
    if article_choice["asked"] or article_choice["hits_checked"] or article_choice["articles_asked"]:
        keys = (
            "offered",
            "chosen",
            "fallback",
            "hits_checked",
            "hits_dropped",
            "hits_fallback",
            "articles_found",
            "articles_fallback",
        )
        front["article_choice"] = {key: article_choice[key] for key in keys}
    if wording is not None:
        front["topic_wording"] = {"topic": wording.topic, "reason": wording.reason, "fallback": wording.fallback}
    if work.enrichment_used in ("model-knowledge", "model-knowledge-full"):
        # The reader has to be able to see this without reading the audit block (docs/umbau.md U4). The note
        # explains marked sentences, so it only appears where there are any - the model may stay in the sources.
        marked = generation_block["marked_sentences"]
        front["enrichment"] = {"mode": work.enrichment_used, "marked_sentences": marked}
        if marked:
            front["enrichment"]["hinweis"] = MODEL_KNOWLEDGE_NOTE
    if note:
        front["note"] = note
    return audit, tokens, front
