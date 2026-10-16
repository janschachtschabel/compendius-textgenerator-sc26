"""Optional static-embedding ranker (Model2Vec). Disabled when no local model is configured."""

from __future__ import annotations

import ctypes
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

# A paragraph at or below this cosine similarity to a block is no candidate for it. M80: from 0 to 0.2 not one of the
# 12,182 paragraphs of 81 topics changes its block - the scores are normalised over the run, and so weak a candidate
# wins nowhere; 0.3 moves 3
MIN_SIMILARITY = 0.1


def _load_model(model_path: str) -> Any:
    from model2vec import StaticModel

    return StaticModel.from_pretrained(model_path)


def _libc() -> Any:
    return ctypes.CDLL("libc.so.6")


def _give_back_freed_memory() -> None:
    """Hand the heap that loading freed back to the system. model2vec 0.10 copies the tokenizer and parses the
    vocabulary while loading; glibc kept the freed memory in the worker: 1,480 MB after loading, 1,003 MB after
    ``malloc_trim(0)``, 1,016 MB after 20 encodes, the vectors the same (measured in the container, audit 2026-10-16,
    C11). Without glibc - Windows, macOS, musl - nothing to do."""
    try:
        _libc().malloc_trim(0)
    except (OSError, AttributeError):
        return


@lru_cache(maxsize=2)
def _model_or_none(model_path: str) -> Any | None:
    """The static model, loaded once per process as matchers are created per request - or ``None`` when it cannot
    be, remembered as well: lru_cache keeps no exceptions, so a wrong MODEL2VEC_PATH was tried and warned about on
    every request, over the network for a path that looks like a Hub repository (audit 2026-09-27, PE-03)."""
    try:
        model = _load_model(model_path)
    except Exception as exc:  # optional dependency, degrade gracefully
        log.warning("Model2Vec model %s not available, not tried again until a restart: %s", model_path, exc)
        return None
    _give_back_freed_memory()
    return model


class Model2VecMatcher:
    name = "model2vec"
    weight = 1.0

    def __init__(self, model_path: str, candidates: int = CANDIDATES_PER_SLOT) -> None:
        self.model_path = model_path
        self.candidates = candidates
        self._model: Any | None = None
        self.available = False
        if model_path:
            self._model = _model_or_none(model_path)
            self.available = self._model is not None

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
                if similarity > MIN_SIMILARITY:
                    raw[slot.id].append((similarity, chunk, f"Model2Vec: {similarity:.2f}"))
        return normalise_candidates(raw, self.name, self.candidates)
