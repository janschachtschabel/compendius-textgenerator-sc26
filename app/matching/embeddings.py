"""Optional static-embedding ranker (Model2Vec). Disabled when no local model is configured."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from functools import lru_cache
from typing import Any

import numpy as np

from app.domain.models import Chunk, ScoredChunk
from app.matching.base import chunk_representation, slot_representation
from app.matching.lexical import CANDIDATES_PER_SLOT, Candidates, normalise_candidates
from app.templates.schema import TemplateSlot

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _load_model(model_path: str) -> Any:
    """Load a static model once per process; matchers are created per request."""
    from model2vec import StaticModel

    return StaticModel.from_pretrained(model_path)


class Model2VecMatcher:
    name = "model2vec"
    weight = 1.0

    def __init__(self, model_path: str, candidates: int = CANDIDATES_PER_SLOT) -> None:
        self.model_path = model_path
        self.candidates = candidates
        self._model: Any | None = None
        self.available = False
        if model_path:
            try:
                self._model = _load_model(model_path)
                self.available = True
            except Exception as exc:  # optional dependency, degrade gracefully
                log.warning("Model2Vec model %s not available: %s", model_path, exc)

    @staticmethod
    def _normalize(matrix: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
        return np.asarray(matrix / np.maximum(norms, 1e-9))

    def score(self, slots: Sequence[TemplateSlot], chunks: Sequence[Chunk]) -> dict[str, list[ScoredChunk]]:
        raw: Candidates = {s.id: [] for s in slots}
        content_slots = [s for s in slots if not s.is_generated]
        if not chunks or self._model is None or not content_slots:
            return {s.id: [] for s in slots}
        chunk_vecs = self._normalize(np.asarray(self._model.encode([chunk_representation(c) for c in chunks])))
        slot_vecs = self._normalize(np.asarray(self._model.encode([slot_representation(s) for s in content_slots])))
        sims = np.asarray(slot_vecs @ chunk_vecs.T)
        for row, slot in zip(sims, content_slots, strict=True):
            for value, chunk in zip(row, chunks, strict=True):
                similarity = float(value)
                if similarity > 0.1:
                    raw[slot.id].append((similarity, chunk, f"Model2Vec: {similarity:.2f}"))
        return normalise_candidates(raw, self.name, self.candidates)
