"""The compendium from what a request made: the switches actually used, the LLM's report, the frontmatter, the
markdown and the audit (PLAN.md 8.1)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from app.compendium.gateway import LlmGateway
from app.compendium.llm_policy import choice_audit
from app.compendium.llm_report import LlmWork, build_llm_report
from app.compendium.prepared import Made
from app.compose.assembler import Switches, build_frontmatter, render_markdown
from app.domain.models import AuditReport, CollectionPart, Compendium, CurriculaPart, SectionStatus
from app.domain.requests import GenerateRequest
from app.knowledge.node_article import node_block
from app.matching.registry import LLM_MATCHER
from app.synthesis.citations import MODEL_KNOWLEDGE_OPEN
from app.synthesis.facets import FacetCatalog
from app.synthesis.lint import lint_sections


def assemble(
    request: GenerateRequest,
    made: Made,
    lap: Callable[[str], None],
    *,
    llm: LlmGateway | None,
    facets: FacetCatalog,
    zim_snapshot: Sequence[Mapping[str, Any]],
) -> Compendium:
    """Put the parts together; ``lap`` records the time of the assembly before the audit is written."""
    prepared, world, requested = made.prepared, made.world, made.requested
    template, sources, chunks = prepared.template, prepared.sources, prepared.chunks
    resolution, topic = prepared.resolution, prepared.title
    sections, citations, matcher_name = world.written.sections, world.written.citations, world.matcher
    curricula, collection_part = made.curricula.part, made.collection
    want_world = "world" in request.parts
    parts = ["world"] if want_world else []
    if curricula is not None:
        parts.append("curricula")
    if collection_part is not None:
        parts.append("collection")

    findings = lint_sections(template, sections, facets)
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    # The switches actually used: a switch without any LLM contribution is rule-based in the compendium.
    extracted, drafted = world.extracted, world.written.llm
    extraction_used = world.extraction if extracted and extracted.slots else "rule-based"
    generation_used = world.generation if drafted and drafted.sections else "rule-based"
    # Enrichment only means something where the LLM actually wrote a block
    enrichment_used = world.enrichment if generation_used != "rule-based" else "sources-only"
    # The blocks a regeneration kept from an earlier compendium: the disclosure follows them too (audit 2026-09-29, A04)
    kept_ids = (
        {slot.id for slot in template.content_slots()} - set(world.regenerated) if request.existing_markdown else set()
    )
    kept = {section.slot_id: section.status for section in sections if section.slot_id in kept_ids}
    kept_model_knowledge = sum(
        section.text.count(MODEL_KNOWLEDGE_OPEN)
        for section in sections
        if section.slot_id in kept_ids and section.status is not SectionStatus.REVIEWED
    )
    node_report = prepared.node_article
    work = LlmWork(
        note=world.llm_note or made.choice_note,
        extraction_requested=requested.extraction,
        extraction_used=extraction_used,
        extraction=extracted,
        generation_requested=requested.generation,
        generation_used=generation_used,
        generation=drafted,
        enrichment_requested=requested.enrichment,
        enrichment_used=enrichment_used,
        matching_requested="llm" if world.matcher_requested == LLM_MATCHER else "rule-based",
        matching_used="llm" if matcher_name == LLM_MATCHER else "rule-based",
        matching=world.matching,
        choice=choice_audit(prepared, made.choice_requested),
        curriculum_requested=made.curricula.requested if curricula is not None else "rule-based",
        curriculum=made.curricula.report,
        curriculum_fallback=made.curricula.fallback,
    )
    llm_audit, llm_tokens, llm_front = build_llm_report(llm, work)
    frontmatter = build_frontmatter(
        topic=topic,
        resolution={
            "query": resolution.query,
            "normalized": resolution.normalized,
            "context": resolution.context,
            "title": resolution.title,
            "path": resolution.path,
            "project": resolution.project,
            "alternatives": resolution.alternatives,
            "method": resolution.method,
            "confident": resolution.confident,
        },
        template=template,
        switches=Switches(
            extraction=extraction_used,
            generation=generation_used,
            enrichment=enrichment_used,
            enriched_sentences=drafted.marked_sentences if drafted else 0,
            matcher=matcher_name,
            extraction_requested=requested.extraction,
            generation_requested=requested.generation,
            matcher_requested=world.matcher_requested,
            kept=kept,
            kept_model_knowledge=kept_model_knowledge,
        ),
        llm=llm_front,
        generated_at=generated_at,
        zim_snapshot=zim_snapshot,
        parts=parts,
    )
    # the sources belong to part 1, with those only its kept blocks cite (audit 2026-09-29, A04)
    source_refs = [s.to_ref() for s in [*sources, *world.carried]] if want_world else []
    markdown = render_markdown(
        topic=topic,
        frontmatter=frontmatter,
        template=template,
        sections=sections,
        sources=source_refs,
        facets_visible=made.facets_visible,
        extra_parts=[part.markdown for part in (curricula, collection_part) if part is not None],
        include_world=want_world,
        include_frontmatter=request.frontmatter_in_markdown,
    )
    lap("assemble")

    filled = sum(1 for s in sections if s.status is not SectionStatus.EMPTY)
    status = parts_status(request, want_world, filled, curricula, collection_part)
    audit = AuditReport(
        preset=request.preset,
        matcher=matcher_name,
        timings_ms=made.timings,
        lint=findings,
        chunks_total=len(chunks),
        chunks_assigned=world.chunks_assigned,
        sections_filled=filled,
        sections_empty=len(sections) - filled,
        citations=len(citations),
        llm_tokens=llm_tokens,
        llm=llm_audit,
        knowledge=prepared.knowledge,
        node_article=node_block(node_report) if node_report is not None else None,
        chunks_truncated=prepared.chunks_truncated,
        parts_status=status,
        regenerated=world.regenerated,
        unattributed_citations=world.unattributed,
    )
    return Compendium(
        topic=topic,
        resolution=resolution,
        template_id=template.id,
        template_version=template.version,
        extraction=extraction_used,
        generation=generation_used,
        enrichment=enrichment_used,
        generated_at=generated_at,
        frontmatter=frontmatter,
        sections=sections,
        curricula=curricula,
        collection=collection_part,
        node=prepared.node,
        sources=source_refs,
        markdown=markdown,
        parts_status=status,
        audit=audit,
    )


def parts_status(
    request: GenerateRequest,
    want_world: bool,
    filled: int,
    curricula: CurriculaPart | None,
    collection: CollectionPart | None,
) -> dict[str, str]:
    """What became of every requested part (PLAN.md 8.1): whole, empty, cut short or not available here."""
    status: dict[str, str] = {}
    if want_world:
        status["world"] = "ok" if filled else "empty"
    if "curricula" in request.parts:
        status["curricula"] = "unavailable" if curricula is None or not curricula.available else "ok"
    if "collection" in request.parts:
        if collection is None or not collection.available:
            status["collection"] = "unavailable"
        else:
            status["collection"] = "incomplete" if collection.summary.get("incomplete") else "ok"
    return status
