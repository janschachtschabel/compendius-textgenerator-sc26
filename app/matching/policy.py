"""Template-driven assignment policy (PLAN.md 4.4, stage 3).

Takes fused candidate scores and decides which chunk goes to which slot: lexicon hits,
lead handling, exclusion penalties, source preferences, global best fit and slot budgets.
No topic-specific vocabulary lives here; everything comes from the template and the lexicon.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.models import Chunk, ScoredChunk, Source, SourceRole, primary_of
from app.knowledge.entities import is_subject
from app.knowledge.topic import TopicMention
from app.matching.base import tokenize
from app.templates.schema import ROLE_KEYS, Template, TemplateSlot

LEXICON_SCORE = 0.9
LEAD_SCORE = 2.0
TWIN_LEAD_SCORE = 1.5
SUBTOPIC_LEAD_SCORE = 0.9
CONFIDENT_SCORE = 0.65  # below this a ranker hit is a guess; topical chunks then take the default slot
MIN_SCORE = 0.25  # score recorded for default-slot assignments (ranks them behind confident hits)
# The factors of _score_candidate (audit 2026-09-27, WA-02). M44 (docs/entwicklung/05-messprotokoll.md) set each
# to 1.0 on the ten gold topics: macro-F1 before the budgets was 0.459 with all of them, and without one as noted.
SUBAREA_BOOST = 1.25  # a side article's introduction that carries the topic, for the overview block; M44: 0.459
OTHER_HEADING_FACTOR = 0.5  # the heading names another block in the lexicon; M44: 0.438 without it
SECTION_LEAD_BOOST = 1.3  # the first paragraph of an H2 section, for the overview block; M44: 0.455
EXCLUSION_FACTOR = 0.6  # a word of the block's exclusions in heading or text; M44: 0.466 without it - Jan decides
FIRST_SOURCE_BOOST = 1.15  # the block's most preferred source project; M44: 0.412 without it
PREFERRED_SOURCE_BOOST = 1.08  # one of its further preferred projects; M44: 0.459


@dataclass
class AssignmentResult:
    assigned: dict[str, list[ScoredChunk]]
    unassigned: int
    notes: list[str] = field(default_factory=list)
    classified: dict[str, str] = field(default_factory=dict)  # chunk id -> slot id before the budgets cut
    # slot id -> chunk id -> the policy's score of the chunk for that slot (> 0): candidates for extraction=llm
    slot_scores: dict[str, dict[str, float]] = field(default_factory=dict)


def exclusion_terms(slot: TemplateSlot) -> set[str]:
    """Signal words from the slot's exclusion text (numbers in brackets are slot references)."""
    text = re.sub(r"\(\s*\d+\s*\)", " ", slot.exclusions)
    return {t for t in tokenize(text) if len(t) >= 5}


@dataclass(frozen=True)
class _Context:
    """What a paragraph's score for a block depends on beyond the two: the topic and the template's roles."""

    topic: TopicMention
    confident_score: float
    # the lexicon keys that mark a definition: the shared lexicon's and the template's definition block
    definition_keys: frozenset[str]

    @classmethod
    def of(cls, template: Template, topic: TopicMention, confident_score: float) -> _Context:
        shared = {key for key, role in ROLE_KEYS.items() if role == "definition"}
        own = {slot.slot for slot in template.slots if slot.role == "definition"}
        return cls(topic, confident_score, frozenset(shared | own))


def _score_candidate(
    slot: TemplateSlot,
    chunk: Chunk,
    fused_score: float,
    source: Source | None,
    exclusions: set[str],
    context: _Context,
) -> tuple[float, list[str]]:
    """A paragraph's score for a block: a fixed one where a rule decides, else the ranker's, weighed in turn by the
    headings, the block's exclusions and the source. Split in three by these steps (audit 2026-09-27, WA-01)."""
    decided = _decided(slot, chunk, source, context)
    if decided is not None:
        return decided
    score, reasons = _by_headings(slot, chunk, fused_score, source, context)
    if exclusions:
        haystack = f"{chunk.full_heading} {chunk.text}".lower()
        hits = [term for term in exclusions if term in haystack]
        if hits:
            score *= EXCLUSION_FACTOR
            reasons.append("Ausschlusssignal: " + ", ".join(sorted(hits)[:3]))
    return _by_source(slot, source, score, reasons, context)


def _decided(
    slot: TemplateSlot, chunk: Chunk, source: Source | None, context: _Context
) -> tuple[float, list[str]] | None:
    """The rules that set a score outright: the leads, the definition block and the introductions of sub-areas."""
    if chunk.is_lead:
        if slot.role == "definition":
            return LEAD_SCORE, ["Lead-Absatz des Hauptartikels"]
        return 0.0, ["Lead gehört in die Themendefinition"]

    is_secondary = source is not None and not source.is_primary
    is_twin_lead = (
        source is not None and source.origin == "same_topic" and chunk.heading_level == 0 and chunk.position == 0
    )

    # Block 1 defines the topic. Its material is the lead of the main article, explicit definition
    # sections of the main article and the plain-language lead of the same topic in another archive.
    if slot.role == "definition":
        if is_twin_lead:
            return TWIN_LEAD_SCORE, ["Einstiegsdefinition aus einem zweiten Archiv"]
        if is_secondary or chunk.lexicon_slot not in context.definition_keys:
            return 0.0, ["Themendefinition nur aus dem Hauptartikel"]
    elif is_twin_lead:
        return 0.0, ["Zwillings-Lead gehört in die Themendefinition"]

    # The lead of a sub-article whose title carries the topic stem describes a
    # sub-area and belongs to block 2; the gold standard confirms this across subjects.
    if (
        is_secondary
        and source is not None
        and source.origin != "same_topic"
        and chunk.heading_level == 0
        and chunk.position == 0
        and context.topic.found_in(source.title)
    ):
        if slot.role == "systematik":
            return SUBTOPIC_LEAD_SCORE, ["Einleitung eines Teilgebiets"]
        return 0.0, ["Teilgebiets-Einleitung gehört in die Systematik"]
    return None


def _by_headings(
    slot: TemplateSlot, chunk: Chunk, score: float, source: Source | None, context: _Context
) -> tuple[float, list[str]]:
    """The ranker's score weighed by what the headings say: the introductions of related articles, the lexicon, the
    first paragraph of a section."""
    reasons: list[str] = []
    lexicon_slot = chunk.lexicon_slot
    is_secondary = source is not None and not source.is_primary
    # Other introductions of related articles (a heading like "Allgemeines") define sub-topics;
    # those that carry the topic in their title lean towards block 2.
    is_intro = chunk.heading_level == 0 or lexicon_slot in context.definition_keys
    if is_secondary and is_intro and source is not None:
        if lexicon_slot in context.definition_keys:
            lexicon_slot = None
        if slot.role == "systematik" and context.topic.found_in(source.title):
            score *= SUBAREA_BOOST
            reasons.append("Teilgebiet des Themas")

    if lexicon_slot:
        if lexicon_slot == slot.slot:
            score = max(score, LEXICON_SCORE)
            reasons.append(f"Überschrift „{chunk.heading}“ im Lexikon")
        else:
            score *= OTHER_HEADING_FACTOR
            reasons.append(f"Überschrift spricht für {lexicon_slot}")

    if slot.role == "systematik" and chunk.is_section_lead:
        score *= SECTION_LEAD_BOOST
        reasons.append("Abschnittseinleitung (H2)")
    return score, reasons


def _by_source(
    slot: TemplateSlot, source: Source | None, score: float, reasons: list[str], context: _Context
) -> tuple[float, list[str]]:
    """The score weighed by the source: the projects the block prefers, and the materials of a collection."""
    if source is not None and slot.source_preference:
        if source.project == slot.source_preference[0]:
            score *= FIRST_SOURCE_BOOST
        elif source.project in slot.source_preference:
            score *= PREFERRED_SOURCE_BOOST

    if source is not None and source.role is SourceRole.MATERIAL and source.project in slot.source_preference:
        # A paragraph of a collection material, whatever its licence (D70), counts as evidence for the blocks that want
        # materials (Bildung, Praxis in sc26); the ranker still orders those blocks among themselves. The
        # score starts at the confidence threshold, so the rule holds whatever threshold is configured.
        score = context.confident_score + (1 - context.confident_score) * min(score, 1.0)
        reasons.append("Material der Wissens-Sammlung")
    return score, reasons


def _is_topical(source: Source | None, topic: TopicMention) -> bool:
    """Main article, its twin in another archive, or a subject article whose title carries the topic.

    Articles about a person, an organisation or a single work (a composer, a film about the
    revolution) mention the topic but are not about it; their body text never fills the default block.
    """
    if source is None:
        return False
    if source.is_primary or source.origin == "same_topic":
        return True
    return topic.found_in(source.title) and is_subject(source)


def assign(
    template: Template,
    chunks: Sequence[Chunk],
    fused: Mapping[str, Sequence[ScoredChunk]],
    sources: Mapping[str, Source],
    confident_score: float = CONFIDENT_SCORE,
) -> AssignmentResult:
    """Assign every chunk to at most one slot (global best fit) within the slot budgets.

    ``confident_score`` is the fused score from which a ranker hit counts as evidence; below it a
    topical chunk takes the template's default slot (setting ``POLICY_CONFIDENT_SCORE``).
    """
    content_slots = template.content_slots()
    fused_lookup: dict[str, dict[str, ScoredChunk]] = {
        slot_id: {sc.chunk.chunk_id: sc for sc in scored} for slot_id, scored in fused.items()
    }
    exclusions = {slot.id: exclusion_terms(slot) for slot in content_slots}
    primary = primary_of(sources.values())
    topic = TopicMention.of(primary.title if primary else "")

    context = _Context.of(template, topic, confident_score)
    generated_keys = template.generated_keys()
    best: dict[str, tuple[str, float, list[str]]] = {}
    slot_scores: dict[str, dict[str, float]] = {slot.id: {} for slot in content_slots}
    skipped = 0
    for chunk in chunks:
        if chunk.lexicon_slot in generated_keys:  # e.g. "Bekannte Vertreter": material for the actors block
            skipped += 1
            continue
        source = sources.get(chunk.source_id)
        candidates: list[tuple[str, float, list[str]]] = []
        for slot in content_slots:
            fused_item = fused_lookup.get(slot.id, {}).get(chunk.chunk_id)
            fused_score = fused_item.score if fused_item else 0.0
            score, reasons = _score_candidate(slot, chunk, fused_score, source, exclusions[slot.id], context)
            if fused_item:
                reasons = [*fused_item.reasons[:3], *reasons]
            candidates.append((slot.id, score, reasons))
            if score > 0:
                slot_scores[slot.id][chunk.chunk_id] = round(score, 4)
        if not candidates:
            continue
        candidates.sort(key=lambda c: -c[1])  # stable: ties keep the template order
        best[chunk.chunk_id] = candidates[0]

    per_slot: dict[str, list[ScoredChunk]] = {slot.id: [] for slot in template.slots}
    chunk_by_id = {c.chunk_id: c for c in chunks}
    default_slot = template.slot_by_key(template.default_slot) if template.default_slot else None
    classified: dict[str, str] = {}
    unassigned = skipped
    for chunk_id, (slot_id, score, reasons) in best.items():
        chunk = chunk_by_id[chunk_id]
        confident = (
            chunk.is_lead or (chunk.lexicon_slot is not None and score >= LEXICON_SCORE) or score >= confident_score
        )
        if not confident:
            # Body text of the topic without a confident signal is subject knowledge (block 3 in
            # sc26); chunks from articles that only mention the topic stay out instead of guessing.
            if default_slot is None or not _is_topical(sources.get(chunk.source_id), topic):
                unassigned += 1
                continue
            slot_id, score = default_slot.id, MIN_SCORE
            reasons = ["Standardbaustein: themennaher Absatz ohne stärkeres Signal"]
        classified[chunk_id] = slot_id
        per_slot[slot_id].append(ScoredChunk(chunk=chunk, score=round(score, 4), matcher="policy", reasons=reasons))

    kept, notes, dropped = cut_to_budgets(template, per_slot)
    return AssignmentResult(
        assigned=kept,
        unassigned=unassigned + dropped,
        notes=notes,
        classified=classified,
        slot_scores=slot_scores,
    )


def cut_to_budgets(
    template: Template, candidates: Mapping[str, Sequence[ScoredChunk]]
) -> tuple[dict[str, list[ScoredChunk]], list[str], int]:
    """The best-scored chunks of every content slot within its budget, lead first and then in reading order.

    Returns the kept chunks for every slot of the template, the notes about cuts and how many chunks were cut.
    """
    kept_per_slot: dict[str, list[ScoredChunk]] = {
        slot.id: list(candidates.get(slot.id, [])) for slot in template.slots
    }
    notes: list[str] = []
    dropped_total = 0
    for slot in template.content_slots():
        # The candidates arrive in corpus order - the main article first, then the others, each in its own order.
        # That is the reading order; the position alone starts at 0 in every article, and sorting by it put the first
        # paragraph of a side article before the second of the main one (audit 2026-09-27, KO-09)
        reading = {item.chunk.chunk_id: index for index, item in enumerate(kept_per_slot[slot.id])}
        items = sorted(kept_per_slot[slot.id], key=lambda sc: (-sc.score, sc.chunk.position))
        kept: list[ScoredChunk] = []
        chars = 0
        for item in items:
            if len(kept) >= slot.budget.max_chunks:
                break
            if kept and len(kept) >= slot.budget.min_chunks and chars >= slot.budget.target_chars * 1.5:
                break
            kept.append(item)
            chars += len(item.chunk.text)
        dropped = len(items) - len(kept)
        if dropped:
            notes.append(f"{slot.id}: {dropped} Kandidaten über Budget verworfen")
            dropped_total += dropped
        # Only the main article's first lead paragraph is marked as the lead (knowledge/segmentation.py), so "lead
        # first" keeps the defining paragraph at the head of its block and moves nothing else: a side article's lead
        # keeps its place in reading order (checked in audit 2026-09-28, KO-30)
        kept_per_slot[slot.id] = sorted(kept, key=lambda sc: (0 if sc.chunk.is_lead else 1, reading[sc.chunk.chunk_id]))
    return kept_per_slot, notes, dropped_total
