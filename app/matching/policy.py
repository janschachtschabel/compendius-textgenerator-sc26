"""Template-driven assignment policy (PLAN.md 4.4, stage 3).

Takes fused candidate scores and decides which chunk goes to which slot: lexicon hits,
lead handling, exclusion penalties, source preferences, global best fit and slot budgets.
No topic-specific vocabulary lives here; everything comes from the template and the lexicon.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.models import Chunk, ScoredChunk, Source, SourceRole
from app.knowledge.entities import is_subject
from app.knowledge.topic import topic_stem
from app.matching.base import tokenize
from app.templates.schema import Template, TemplateSlot

LEXICON_SCORE = 0.9
LEAD_SCORE = 2.0
TWIN_LEAD_SCORE = 1.5
SUBTOPIC_LEAD_SCORE = 0.9
CONFIDENT_SCORE = 0.65  # below this a ranker hit is a guess; topical chunks then take the default slot
MIN_SCORE = 0.25  # score recorded for default-slot assignments (ranks them behind confident hits)
MATERIAL_SCORE = CONFIDENT_SCORE  # a curated OER material starts at the confidence threshold (PLAN.md 6.3, D24)
DOUBT_MARGIN = 0.1  # two slots this close are a doubtful case for the LLM router (PLAN.md 4.4, phase 5)
DOUBT_FLOOR = 0.45  # close calls count from here, also below the confidence threshold: that band is the router's
DOUBT_CANDIDATES = 3
DEFINITION_SLOT_KEYS = ("themendefinition", "definition")
SYSTEMATIK_SLOT_KEYS = ("systematik",)


@dataclass
class Doubt:
    """A chunk whose two best slots lie within ``DOUBT_MARGIN``; ``candidates`` are (slot id, score), best first."""

    chunk_id: str
    candidates: list[tuple[str, float]]

    @property
    def margin(self) -> float:
        return self.candidates[0][1] - self.candidates[1][1] if len(self.candidates) > 1 else 1.0


@dataclass
class AssignmentResult:
    assigned: dict[str, list[ScoredChunk]]
    unassigned: int
    notes: list[str] = field(default_factory=list)
    classified: dict[str, str] = field(default_factory=dict)  # chunk id -> slot id before the budgets cut
    doubtful: list[Doubt] = field(default_factory=list)  # close calls the LLM router may decide (hybrid modes)


def exclusion_terms(slot: TemplateSlot) -> set[str]:
    """Signal words from the slot's exclusion text (numbers in brackets are slot references)."""
    text = re.sub(r"\(\s*\d+\s*\)", " ", slot.exclusions)
    return {t for t in tokenize(text) if len(t) >= 5}


def _score_candidate(
    slot: TemplateSlot,
    chunk: Chunk,
    fused_score: float,
    source: Source | None,
    exclusions: set[str],
    primary_stem: str,
    confident_score: float = CONFIDENT_SCORE,
) -> tuple[float, list[str]]:
    score = fused_score
    reasons: list[str] = []

    if chunk.is_lead:
        if slot.slot in DEFINITION_SLOT_KEYS:
            return LEAD_SCORE, ["Lead-Absatz des Hauptartikels"]
        return 0.0, ["Lead gehört in die Themendefinition"]

    lexicon_slot = chunk.lexicon_slot
    is_secondary = source is not None and not source.is_primary
    is_twin_lead = (
        source is not None and source.origin == "same_topic" and chunk.heading_level == 0 and chunk.position == 0
    )

    # Block 1 defines the topic. Its material is the lead of the main article, explicit definition
    # sections of the main article and the plain-language lead of the same topic in another archive.
    if slot.slot in DEFINITION_SLOT_KEYS:
        if is_twin_lead:
            return TWIN_LEAD_SCORE, ["Einstiegsdefinition aus einem zweiten Archiv"]
        if is_secondary or lexicon_slot not in DEFINITION_SLOT_KEYS:
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
        and primary_stem
        and primary_stem in source.title.lower()
    ):
        if slot.slot in SYSTEMATIK_SLOT_KEYS:
            return SUBTOPIC_LEAD_SCORE, ["Einleitung eines Teilgebiets"]
        return 0.0, ["Teilgebiets-Einleitung gehört in die Systematik"]

    # Other introductions of related articles (a heading like "Allgemeines") define sub-topics;
    # those that carry the topic in their title lean towards block 2.
    is_intro = chunk.heading_level == 0 or lexicon_slot in DEFINITION_SLOT_KEYS
    if is_secondary and is_intro and source is not None:
        if lexicon_slot in DEFINITION_SLOT_KEYS:
            lexicon_slot = None
        if slot.slot in SYSTEMATIK_SLOT_KEYS and primary_stem and primary_stem in source.title.lower():
            score *= 1.25
            reasons.append("Teilgebiet des Themas")

    if lexicon_slot:
        if lexicon_slot == slot.slot:
            score = max(score, LEXICON_SCORE)
            reasons.append(f"Überschrift „{chunk.heading}“ im Lexikon")
        else:
            score *= 0.5
            reasons.append(f"Überschrift spricht für {lexicon_slot}")

    if slot.slot in SYSTEMATIK_SLOT_KEYS and chunk.is_section_lead:
        score *= 1.3
        reasons.append("Abschnittseinleitung (H2)")

    if exclusions:
        haystack = f"{chunk.full_heading} {chunk.text}".lower()
        hits = [term for term in exclusions if term in haystack]
        if hits:
            score *= 0.6
            reasons.append("Ausschlusssignal: " + ", ".join(sorted(hits)[:3]))

    if source is not None and slot.source_preference:
        if source.project == slot.source_preference[0]:
            score *= 1.15
        elif source.project in slot.source_preference:
            score *= 1.08

    if source is not None and source.role is SourceRole.MATERIAL and source.project in slot.source_preference:
        # A paragraph of a reusable collection material counts as evidence for the blocks that want
        # materials (Bildung, Praxis in sc26); the ranker still orders those blocks among themselves. The
        # score starts at the confidence threshold, so the rule holds whatever threshold is configured.
        score = confident_score + (1 - confident_score) * min(score, 1.0)
        reasons.append("Material der Wissens-Sammlung")

    return score, reasons


def _is_topical(source: Source | None, primary_stem: str) -> bool:
    """Main article, its twin in another archive, or a subject article whose title carries the topic.

    Articles about a person, an organisation or a single work (a composer, a film about the
    revolution) mention the topic but are not about it; their body text never fills the default block.
    """
    if source is None:
        return False
    if source.is_primary or source.origin == "same_topic":
        return True
    return bool(primary_stem) and primary_stem in source.title.lower() and is_subject(source)


def assign(
    template: Template,
    chunks: Sequence[Chunk],
    fused: Mapping[str, Sequence[ScoredChunk]],
    sources: Mapping[str, Source],
    confident_score: float = CONFIDENT_SCORE,
    overrides: Mapping[str, str] | None = None,
) -> AssignmentResult:
    """Assign every chunk to at most one slot (global best fit) within the slot budgets.

    ``confident_score`` is the fused score from which a ranker hit counts as evidence; below it a
    topical chunk takes the template's default slot (setting ``POLICY_CONFIDENT_SCORE``).
    ``overrides`` (chunk id -> slot id) are decisions of the LLM router for doubtful cases; they count
    as confident hits, unknown slot ids are ignored.
    """
    content_slots = template.content_slots()
    fused_lookup: dict[str, dict[str, ScoredChunk]] = {
        slot_id: {sc.chunk.chunk_id: sc for sc in scored} for slot_id, scored in fused.items()
    }
    exclusions = {slot.id: exclusion_terms(slot) for slot in content_slots}
    primary = next((s for s in sources.values() if s.is_primary), None)
    primary_stem = topic_stem(primary.title) if primary else ""

    generated_keys = {slot.slot for slot in template.slots if slot.is_generated}
    content_ids = {slot.id for slot in content_slots}
    best: dict[str, tuple[str, float, list[str]]] = {}
    doubtful: list[Doubt] = []
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
            score, reasons = _score_candidate(
                slot, chunk, fused_score, source, exclusions[slot.id], primary_stem, confident_score
            )
            if fused_item:
                reasons = [*fused_item.reasons[:3], *reasons]
            candidates.append((slot.id, score, reasons))
        if not candidates:
            continue
        candidates.sort(key=lambda c: -c[1])  # stable: ties keep the template order
        override = overrides.get(chunk.chunk_id) if overrides else None
        if override in content_ids:
            slot_id, score, reasons = next(c for c in candidates if c[0] == override)
            best[chunk.chunk_id] = (
                slot_id,
                max(score, confident_score),
                [*reasons, "LLM-Router: Zweifelsfall zugeordnet"],
            )
            continue
        best[chunk.chunk_id] = candidates[0]
        doubt = _doubt(chunk, candidates)
        if doubt is not None:
            doubtful.append(doubt)

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
            if default_slot is None or not _is_topical(sources.get(chunk.source_id), primary_stem):
                unassigned += 1
                continue
            slot_id, score = default_slot.id, MIN_SCORE
            reasons = ["Standardbaustein: themennaher Absatz ohne stärkeres Signal"]
        classified[chunk_id] = slot_id
        per_slot[slot_id].append(ScoredChunk(chunk=chunk, score=round(score, 4), matcher="policy", reasons=reasons))

    notes: list[str] = []
    for slot in content_slots:
        items = sorted(per_slot[slot.id], key=lambda sc: (-sc.score, sc.chunk.position))
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
            unassigned += dropped
        per_slot[slot.id] = sorted(kept, key=lambda sc: (0 if sc.chunk.is_lead else 1, sc.chunk.position))
    return AssignmentResult(
        assigned=per_slot, unassigned=unassigned, notes=notes, classified=classified, doubtful=doubtful
    )


def _doubt(chunk: Chunk, candidates: Sequence[tuple[str, float, list[str]]]) -> Doubt | None:
    """A close call: best slot at least ``DOUBT_FLOOR`` and below a lexicon hit, second within ``DOUBT_MARGIN``."""
    if chunk.is_lead or len(candidates) < 2:
        return None
    best_score, second_score = candidates[0][1], candidates[1][1]
    if not (DOUBT_FLOOR <= best_score < LEXICON_SCORE) or second_score <= 0:
        return None
    if best_score - second_score >= DOUBT_MARGIN:
        return None
    top = [(slot_id, round(score, 4)) for slot_id, score, _ in candidates[:DOUBT_CANDIDATES] if score > 0]
    return Doubt(chunk_id=chunk.chunk_id, candidates=top)
