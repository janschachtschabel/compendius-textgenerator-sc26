"""Core data model (PLAN.md, section 3.4): sources, chunks, sections, compendium."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class SourceRole(StrEnum):
    """Role a source plays in the corpus; derived from the archive project."""

    LEITQUELLE = "leitquelle"
    EINFACHE_SPRACHE = "einfache_sprache"
    LEHRBUCH = "lehrbuch"
    HOCHSCHULE = "hochschule"
    MATERIAL = "material"
    SONSTIGE = "sonstige"


class ChunkKind(StrEnum):
    TEXT = "text"
    LIST = "list"
    TABLE = "table"


LEAD_CHARS = 400  # a preview, not the article


def collapse_lead(text: str) -> str:
    """The first sentences of a lead on one line, capped for API answers."""
    single = " ".join(text.split())
    return single if len(single) <= LEAD_CHARS else single[: LEAD_CHARS - 1].rstrip() + "…"


class Paragraph(BaseModel):
    """One block of an article section."""

    kind: ChunkKind = ChunkKind.TEXT
    text: str


class ArticleSection(BaseModel):
    """A section of an article: heading path and its blocks. The lead has an empty heading."""

    heading: str = ""
    path: list[str] = Field(default_factory=list)
    level: int = 0
    paragraphs: list[Paragraph] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list, description="Internal link titles in document order")

    @property
    def is_lead(self) -> bool:
        return self.level == 0


class Source(BaseModel):
    """A normalised article from one archive, with provenance."""

    source_id: str
    project: str
    role: SourceRole = SourceRole.SONSTIGE
    title: str
    url: str
    zim_file: str | None = None
    zim_uuid: str | None = None
    zim_date: str | None = None
    entry_path: str | None = None
    license: str = "CC BY-SA 4.0"
    authors: list[str] = Field(default_factory=list, description="Named authors; empty for wiki projects")
    language: str = "de"
    authority_score: float = 1.0
    is_primary: bool = False
    origin: str = Field("primary", description="primary | same_topic | linked | search | lookup")
    aliases: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    reference_lines: list[str] = Field(default_factory=list, description="Lines from Literatur/Weblinks sections")
    relation_titles: list[str] = Field(default_factory=list, description="Titles from 'Siehe auch' sections")
    sections: list[ArticleSection] = Field(default_factory=list)

    @property
    def lead_text(self) -> str:
        for section in self.sections:
            if section.is_lead:
                return "\n\n".join(p.text for p in section.paragraphs)
        return ""

    def to_ref(self) -> SourceRef:
        return SourceRef(
            lead=collapse_lead(self.lead_text),
            source_id=self.source_id,
            project=self.project,
            role=self.role,
            title=self.title,
            url=self.url,
            zim_file=self.zim_file,
            zim_date=self.zim_date,
            license=self.license,
            authors=list(self.authors),
            authority_score=self.authority_score,
            is_primary=self.is_primary,
        )


class SourceRef(BaseModel):
    """Lightweight source description for API output and the sources section."""

    source_id: str
    project: str
    role: SourceRole
    title: str
    url: str
    zim_file: str | None = None
    zim_date: str | None = None
    license: str
    authors: list[str] = Field(default_factory=list)
    authority_score: float
    is_primary: bool
    lead: str = Field("", description="Beginning of the article's lead paragraph, for callers that show a preview")


class Chunk(BaseModel):
    """A segment of a source: one paragraph, list or table under a heading path."""

    chunk_id: str
    source_id: str
    heading: str
    heading_path: list[str] = Field(default_factory=list)
    heading_level: int = 0
    is_lead: bool = False
    is_section_lead: bool = False
    kind: ChunkKind = ChunkKind.TEXT
    text: str
    position: int = 0
    lexicon_slot: str | None = None

    @property
    def full_heading(self) -> str:
        return " > ".join(self.heading_path) if self.heading_path else "Einleitung"


class ScoredChunk(BaseModel):
    chunk: Chunk
    score: float
    matcher: str = ""
    reasons: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    number: int
    source_id: str
    chunk_id: str
    source_title: str
    source_url: str
    section_heading: str
    snippet: str


class SectionStatus(StrEnum):
    EXTRACTIVE = "maschinell-extraktiv"
    GENERATED = "maschinell-generiert"
    LLM = "ki-generiert"
    # verbatim source text an LLM chose: its sentences (extraction=llm, D33) or its paragraphs (matcher=llm, D34)
    LLM_SELECTED = "ki-ausgewählt"
    REVIEWED = "redaktionell-geprüft"
    EMPTY = "leer"


class Section(BaseModel):
    """One building block of part 1."""

    slot_id: str
    slot_key: str
    title: str
    text: str = ""
    citations: list[Citation] = Field(default_factory=list)
    facets: dict[str, list[str]] = Field(default_factory=dict)
    chunk_ids: list[str] = Field(default_factory=list)
    status: SectionStatus = SectionStatus.EMPTY
    matching: dict[str, Any] = Field(default_factory=dict)
    llm: dict[str, Any] | None = Field(
        None, description="Prompt id and version, model, tokens and dropped sentences when the LLM wrote the text"
    )


class Resolution(BaseModel):
    """How the input was turned into an article title."""

    query: str
    normalized: str
    context: list[str] = Field(default_factory=list)
    title: str | None = None
    path: str | None = None
    project: str | None = None
    alternatives: list[str] = Field(default_factory=list)
    disambiguation: bool = False
    # title (exact or redirect), variant (inflected form, compound, aspect), disambiguation, suggestion, search,
    # or llm (article_choice=llm decided an unsure resolution, D35)
    method: str | None = None
    confident: bool = Field(
        False, description="False for guesses: title suggestions, full-text hits and meanings nothing spoke for"
    )
    # The meanings of the disambiguation page the rules weighed: what article_choice=llm chooses from; not in the API
    _meanings: list[str] = PrivateAttr(default_factory=list)

    @property
    def resolved(self) -> bool:
        return self.title is not None


class LintFinding(BaseModel):
    rule: str
    severity: str = "warning"
    section_id: str | None = None
    message: str


class AuditReport(BaseModel):
    matcher: str | None = Field(None, description="Matching strategy of part 1; null without part 1")
    timings_ms: dict[str, int] = Field(default_factory=dict)
    lint: list[LintFinding] = Field(default_factory=list)
    chunks_total: int = 0
    chunks_truncated: int = Field(0, description="Paragraphs left out by the CORPUS_MAX_CHUNKS cap")
    chunks_assigned: int = 0
    sections_filled: int = 0
    sections_empty: int = 0
    citations: int = 0
    llm_tokens: dict[str, int] | None = Field(None, description="prompt, completion, total, calls (LLM switches)")
    llm: dict[str, Any] | None = Field(
        None,
        description="LLM switches: extraction and generation (requested, used, blocks, fallbacks), note",
    )
    knowledge: dict[str, Any] | None = Field(
        None, description="Knowledge collection: materials considered, used, failed"
    )
    parts_status: dict[str, str] = Field(
        default_factory=dict, description="Per requested part: ok, empty, incomplete or unavailable"
    )
    regenerated: list[str] = Field(
        default_factory=list, description="Blocks made anew although an earlier text was given (PLAN.md 4.6)"
    )


class CollectionPart(BaseModel):
    """Part 3: overview of the collection the compendium belongs to (PLAN.md 6)."""

    available: bool = Field(description="False when the repository could not be read; markdown then holds a hint")
    collection_id: str
    title: str = ""
    summary: dict[str, Any] = Field(default_factory=dict)
    markdown: str = ""
    error: str | None = None


class CurriculaPart(BaseModel):
    """Part 2: curriculum references from the local MEM cache (PLAN.md 5)."""

    available: bool = Field(description="False when no harvested cache exists; markdown then holds a hint")
    keywords: list[str] = Field(default_factory=list)
    subject_terms: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    entries: list[dict[str, Any]] = Field(default_factory=list, description="Ranked matches, flat for API consumers")
    markdown: str = ""


class Compendium(BaseModel):
    """The generated result: part 1 sections, optional part 2, provenance and audit."""

    topic: str
    resolution: Resolution
    template_id: str
    template_version: int
    extraction: str = Field(description="Extraction switch actually used: rule-based or llm")
    generation: str = Field(description="Generation switch actually used: rule-based, llm-fast or llm")
    enrichment: str = Field(
        "sources-only",
        description="Enrichment actually in effect: sources-only, or model-knowledge when the LLM was allowed "
        "to add knowledge of its own (marked in the text, counted per block)",
    )
    generated_at: str
    frontmatter: dict[str, Any] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list)
    curricula: CurriculaPart | None = None
    collection: CollectionPart | None = None
    sources: list[SourceRef] = Field(default_factory=list)
    markdown: str = ""
    parts_status: dict[str, str] = Field(
        default_factory=dict,
        description="Per requested part: ok (whole), empty (nothing found), incomplete (cut short), unavailable",
    )
    audit: AuditReport
