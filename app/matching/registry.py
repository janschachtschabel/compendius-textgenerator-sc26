"""Matching strategies. All strategies return fused candidates; the policy assigns."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.domain.models import Chunk, ScoredChunk
from app.matching.base import Matcher
from app.matching.embeddings import Model2VecMatcher
from app.matching.fusion import fuse_rankings
from app.matching.lexical import BM25Matcher, CharTfidfMatcher
from app.templates.schema import TemplateSlot


class UnknownMatcherError(ValueError):
    """No matching strategy with this id; the message is the id."""


class LexiconOnlyMatcher:
    """No ranking at all: only heading-lexicon hits and the lead are assigned by the policy."""

    name = "lexicon_only"
    weight = 1.0

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]:
        return {s.id: [] for s in slots}


class HybridLightMatcher:
    """BM25 + character TF-IDF (+ Model2Vec when a local model is configured), score fused."""

    name = "hybrid_light"
    weight = 1.0

    def __init__(self, model2vec_path: str = "") -> None:
        self.components: list[Matcher] = [BM25Matcher(), CharTfidfMatcher()]
        embeddings = Model2VecMatcher(model2vec_path) if model2vec_path else None
        if embeddings is not None and embeddings.available:
            self.components.append(embeddings)

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]:
        rankings = [component.score(slots, chunks) for component in self.components]
        fused = fuse_rankings(rankings, [component.weight for component in self.components])
        for slot in slots:
            fused.setdefault(slot.id, [])
        return fused


STRATEGIES: dict[str, dict[str, Any]] = {
    "hybrid_light": {
        "name": "Hybrid light (Lexikon + BM25 + Char-TF-IDF, optional Model2Vec)",
        "cost": "0 €",
        "hardware": "CPU",
        "recommended": True,
    },
    "bm25": {"name": "Okapi BM25", "cost": "0 €", "hardware": "CPU", "recommended": False},
    "char_tfidf": {"name": "Zeichen-TF-IDF (Komposita)", "cost": "0 €", "hardware": "CPU", "recommended": False},
    "lexicon_only": {"name": "Nur Überschriften-Lexikon", "cost": "0 €", "hardware": "CPU", "recommended": False},
}


def ensure_strategy(name: str) -> str:
    """Return ``name`` when it is a known strategy id; raise ``UnknownMatcherError`` otherwise."""
    if name not in STRATEGIES:
        raise UnknownMatcherError(name)
    return name


def get_matcher(name: str, model2vec_path: str = "") -> Matcher:
    if name == "hybrid_light":
        return HybridLightMatcher(model2vec_path)
    if name == "bm25":
        return BM25Matcher()
    if name == "char_tfidf":
        return CharTfidfMatcher()
    if name == "lexicon_only":
        return LexiconOnlyMatcher()
    raise UnknownMatcherError(name)


def list_strategies() -> list[dict[str, Any]]:
    return [{"id": key, **meta} for key, meta in STRATEGIES.items()]
