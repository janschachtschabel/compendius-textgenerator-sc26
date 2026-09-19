"""Between the legacy contract and the orchestrator (PLAN.md 8.1): request in, compendium out.

The old service asked an LLM for entities and then for one text. The new one resolves the topic in the
archives and assembles the compendium, so the legacy answer is built from that result: ``markdown`` is the whole
compendium, ``bibliography`` its sources block, ``linker_output`` a shim over the resolved articles, and
``statistics`` keeps the old keys and adds the audit. Options the new service has no use for are named in
``statistics.notes``; nothing is dropped in silence.
"""

from __future__ import annotations

import re
from typing import Any

from app.api.v1.models import (
    CompendiumConfig,
    CompendiumResponse,
    Entity,
    EntityDetails,
    EntitySources,
    LinkerConfig,
    LinkerOutput,
    WikipediaSource,
)
from app.domain.models import Compendium, SourceRef
from app.domain.requests import NODE_ID_PATTERN, GenerateRequest

TARGET_LENGTH_MIN, TARGET_LENGTH_MAX = 2_000, 60_000
NODE_ID_RE = re.compile(NODE_ID_PATTERN)
SOURCES_SLOT_KEY = "quellen"
PRIMARY_TYPE, RELATED_TYPE = "TOPIC", "RELATED"


class UnsupportedOptionError(ValueError):
    """An option of the old contract the new service refuses instead of answering something else."""


def topic_of_linker_data(linker_data: dict[str, Any]) -> tuple[str, int]:
    """The topic a linker output stands for and how many entities it names (PLAN.md 8.1: labels as topics)."""
    entities = linker_data.get("entities")
    labels = (
        [
            str(entity["entity"]).strip()
            for entity in entities
            if isinstance(entity, dict) and str(entity.get("entity") or "").strip()
        ]
        if isinstance(entities, list)
        else []
    )
    text = str(linker_data.get("original_text") or "").strip()
    return (text or (labels[0] if labels else "")), len(labels)


def build_request(text: str | None, config: CompendiumConfig, notes: list[str]) -> GenerateRequest:
    """The v2 request behind a legacy call; ``notes`` collects what the caller should know about the mapping."""
    if config.language != "de":
        raise UnsupportedOptionError("Der Dienst erzeugt nur Deutsch (language=de)")
    if not config.enable_citations:
        notes.append("enable_citations=false: Belege gehören zu jedem Baustein und bleiben erhalten")
    if not config.educational_mode:
        notes.append("educational_mode=false: der Dienst erzeugt immer das kompendiale Template")
    target_length = min(max(config.length, TARGET_LENGTH_MIN), TARGET_LENGTH_MAX)
    if target_length != config.length:
        notes.append(f"length={config.length} liegt außerhalb von {TARGET_LENGTH_MIN}–{TARGET_LENGTH_MAX} Zeichen")
    collection_id = config.collection_id
    topic: str | None = text
    if text and NODE_ID_RE.match(text.strip()):  # a nodeId in text is the collection (D12)
        collection_id, topic = text.strip(), None
        notes.append("text ist eine nodeId und wurde als Sammlung gelesen")
    fields: dict[str, Any] = {
        "topic": topic,
        "collection_id": collection_id,
        "knowledge_collection_id": config.knowledge_collection_id,
        "subject": config.subject,
        "template_id": config.template_id,
        "target_length": target_length,
        "extraction": config.extraction,
        "generation": config.generation,
    }
    if config.parts is not None:
        fields["parts"] = config.parts
    return GenerateRequest(**fields)


def note_linker_config(config: LinkerConfig, notes: list[str]) -> None:
    """The linker settings of the old pipeline: the new service reads the archives instead of asking an LLM (D14)."""
    if config.MODE != "extract" or config.MAX_ENTITIES != 10 or config.ALLOWED_ENTITY_TYPES != "auto":
        notes.append("config.linker: die Artikel kommen aus den Archiven, MODE/MAX_ENTITIES/Typen steuern nichts")
    if config.LANGUAGE != "de":
        raise UnsupportedOptionError("Der Dienst erzeugt nur Deutsch (config.linker.LANGUAGE=de)")


def bibliography(compendium: Compendium) -> str:
    """The sources block of the compendium, with its heading, as the old ``bibliography``."""
    for section in compendium.sections:
        if section.slot_key == SOURCES_SLOT_KEY and section.text:
            return f"## {section.title}\n\n{section.text}"
    return "## Quellen\n\n*Keine Quellen verfügbar.*"


def statistics(compendium: Compendium, *, input_type: str, notes: list[str], **extra: int) -> dict[str, Any]:
    """The old keys plus the audit of the new service; ``extra`` carries ``input_length`` or ``entities_count``."""
    audit = compendium.audit
    return {
        "topic": compendium.topic,
        "input_type": input_type,
        **extra,
        "output_length": len(compendium.markdown),
        "references_count": len(compendium.sources),
        "educational_mode": True,
        "citations_enabled": True,
        "notes": notes,
        "audit": {
            "template": compendium.template_id,
            "template_version": compendium.template_version,
            "matcher": audit.matcher,
            "extraction": compendium.extraction,
            "generation": compendium.generation,
            "parts": compendium.frontmatter.get("parts", []),
            "parts_status": compendium.parts_status,
            "sections_filled": audit.sections_filled,
            "sections_empty": audit.sections_empty,
            "citations": audit.citations,
            "chunks_total": audit.chunks_total,
            "chunks_assigned": audit.chunks_assigned,
            "timings_ms": audit.timings_ms,
            "llm_tokens": audit.llm_tokens,
        },
    }


def compendium_response(
    compendium: Compendium, *, input_type: str, notes: list[str], **extra: int
) -> CompendiumResponse:
    return CompendiumResponse(
        markdown=compendium.markdown,
        bibliography=bibliography(compendium),
        statistics=statistics(compendium, input_type=input_type, notes=notes, **extra),
    )


def linker_output(compendium: Compendium, text: str) -> LinkerOutput:
    """The resolved articles in the shape the old linker answered with (label, link, lead as extract)."""
    return LinkerOutput(original_text=text, entities=[_entity(source) for source in compendium.sources])


def _entity(source: SourceRef) -> Entity:
    kind = PRIMARY_TYPE if source.is_primary else RELATED_TYPE
    return Entity(
        entity=source.title,
        details=EntityDetails(typ=kind, citation=source.title),
        sources=EntitySources(
            wikipedia=WikipediaSource(
                status="found",
                label_de=source.title,
                url_de=source.url,
                extract=source.lead or None,
            )
        ),
    )
